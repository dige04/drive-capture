/**
 * Drive Capture Extension - Background Service Worker
 * Merged logic for robust connection with Python worker and legacy URL capture
 */

// ============ Configuration ============
const HOST_ID = 'com.drivecapture.worker';
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]; // Exponential backoff
const CAPTURE_TIMEOUT = 5000; // 5 seconds

// ============ State ============
let port = null;
let connected = false;
let reconnectAttempt = 0;
let reconnectTimer = null;
let lastMessageAt = Date.now();
let lastReloadAt = 0;
const RELOAD_COOLDOWN_MS = 180000; // 3 minutes

// Legacy capture state
let capturedRequests = {}; // Stores network requests for URL extraction
let activeTabs = new Set(); // Tracks tabs opened by the extension

// ============ Connection Management ============
function connect() {
    try {
        console.log(`[Connect] Attempting connection to ${HOST_ID}...`);
        port = chrome.runtime.connectNative(HOST_ID);
        
        port.onMessage.addListener(handleMessage);
        port.onDisconnect.addListener(handleDisconnect);
        
        // Send initial handshake
        sendMessage({ type: 'hello', version: '2.0' });
        
    } catch (error) {
        console.error('[Connect] Failed:', error);
        scheduleReconnect();
    }
}

function handleMessage(msg) {
    lastMessageAt = Date.now();
    console.log('[Message]', msg);
    
    switch(msg.type) {
        case 'ready':
            connected = true;
            reconnectAttempt = 0;
            console.log('[Connected] Worker ready');
            break;
            
        case 'ping':
            sendMessage({ type: 'pong' });
            break;
            
        case 'capture':
            // Trigger legacy capture logic
            startLegacyCapture(msg.file_id);
            break;
            
        case 'rclone_status':
            console.log(`[Rclone Status] ${msg.file_id}: ${msg.status} - ${msg.file_name}`);
            if (msg.error) {
                console.error(`[Rclone Status] Error: ${msg.error}`);
            }
            break;

        case 'rclone_progress':
            console.log(`[Rclone Progress] ${msg.file_id}: ${msg.progress}`);
            break;

        case 'rclone_error':
            console.error(`[Rclone Error] ${msg.file_id}: ${msg.error}`);
            break;
        
        case 'reset_requested':
            console.warn(`[Reset] Worker requested reset: ${msg.reason || 'no reason provided'}`);
            // Reload the extension to get a clean state and reconnect to native host
            try {
                const now = Date.now();
                if (now - lastReloadAt > RELOAD_COOLDOWN_MS) {
                    lastReloadAt = now;
                    chrome.runtime.reload();
                } else {
                    console.warn('[Reset] Ignored due to cooldown');
                }
            } catch (e) {
                console.warn('[Reset] Reload failed, trying to restart native connection');
                try { if (port) port.disconnect(); } catch (_) {}
            }
            break;
            
        default:
            console.log('[Message] Unknown type:', msg.type);
    }
}

function handleDisconnect() {
    console.log('[Disconnect] Port disconnected');
    connected = false;
    port = null;
    
    // Clean up tabs opened by the extension
    for (let tabId of activeTabs) {
        cleanupTabResources(tabId);
    }
    activeTabs.clear();
    
    scheduleReconnect();
}

function scheduleReconnect() {
    if (reconnectTimer) return;
    
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)];
    console.log(`[Reconnect] Scheduling in ${delay}ms (attempt ${reconnectAttempt + 1})`);
    
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        reconnectAttempt++;
        connect();
    }, delay);
}

function sendMessage(msg) {
    if (!port) {
        console.warn('[Send] No port available');
        return false;
    }
    
    try {
        port.postMessage(msg);
        return true;
    } catch (error) {
        console.error('[Send] Failed:', error);
        return false;
    }
}

// ============ Legacy Capture Logic ============

// Cleans up resources associated with a tab
function cleanupTabResources(tabId) {
    const debuggee = { tabId: tabId };
    // Clear any pending promises for this tab
    if (capturedRequests[tabId]) {
        clearTimeout(capturedRequests[tabId].timeoutId);
        delete capturedRequests[tabId];
    }

    chrome.debugger.detach(debuggee, () => {
        if (chrome.runtime.lastError) {
            // console.warn(`[Cleanup] Detach failed for tab ${tabId}:`, chrome.runtime.lastError.message);
        }
    });
    activeTabs.delete(tabId);
    chrome.tabs.remove(tabId).catch(() => {}); // Close the tab
}

// Initiates the two-step capture process (load, then reload on timeout)
async function startLegacyCapture(fileId) {
    let tabId;

    try {
        // 1. Open tab and attach debugger
        const url = `https://drive.google.com/file/d/${fileId}/view`;
        const tab = await chrome.tabs.create({ url, active: false });
        tabId = tab.id;
        activeTabs.add(tabId);

        const debuggee = { tabId: tabId };
        await chrome.debugger.attach(debuggee, "1.3");
        await chrome.debugger.sendCommand(debuggee, "Network.enable");

        // 2. First Attempt (Initial Load)
        try {
            console.log(`[Capture] Attempt 1 (New Tab) for ${fileId}`);
            const videoUrl = await new Promise((resolve, reject) => {
                const timeoutId = setTimeout(() => reject(new Error('Timeout on initial load')), CAPTURE_TIMEOUT);
                capturedRequests[tabId] = { resolve, reject, timeoutId };
            });

            console.log(`[Capture] Success on initial load for ${fileId}`);
            // Send both primary URL and all candidate URLs if available (filled in debugger listener)
            const urls = capturedRequests[tabId]?.urls || undefined;
            sendResult(fileId, videoUrl, null, urls);
            cleanupTabResources(tabId);
            return; // Success, so we are done.

        } catch (error) {
            console.warn(`[Capture] Timed out on initial load for ${fileId}. Reloading...`);
            // The promise for the first attempt was rejected by the timeout.
            // We can now proceed to the reload attempt.
        }

        // 3. Second Attempt (Reload)
        chrome.tabs.reload(tabId);

        try {
            console.log(`[Capture] Attempt 2 (Reload) for ${fileId}`);
            const videoUrl = await new Promise((resolve, reject) => {
                const timeoutId = setTimeout(() => reject(new Error('Timeout after reload')), CAPTURE_TIMEOUT);
                capturedRequests[tabId] = { resolve, reject, timeoutId };
            });

            console.log(`[Capture] Success after reload for ${fileId}`);
            const urls = capturedRequests[tabId]?.urls || undefined;
            sendResult(fileId, videoUrl, null, urls);

        } catch (error) {
            console.error(`[Capture] Failed to capture ${fileId} after reload.`);
            sendResult(fileId, null, error.message, undefined);
        }

    } catch (criticalError) {
        // This catches errors from tab creation or debugger attachment
        console.error(`[Capture] A critical error occurred for ${fileId}:`, criticalError.message);
        sendResult(fileId, null, criticalError.message, undefined);
    } finally {
        // 4. Cleanup
        if (tabId) {
            cleanupTabResources(tabId);
        }
    }
}

function sendResult(fileId, url, error, urls) {
    sendMessage({
        type: 'result',
        file_id: fileId,
        url: url,
        error: error,
        urls: urls
    });
}

// ============ Chrome Events (Legacy Logic) ============

chrome.tabs.onRemoved.addListener((tabId) => {
    if (activeTabs.has(tabId)) {
        console.log(`[Cleanup] Tab ${tabId} removed unexpectedly.`);
        // Reject any pending promise for this tab
        if (capturedRequests[tabId] && capturedRequests[tabId].reject) {
            capturedRequests[tabId].reject(new Error('Tab closed unexpectedly'));
        }
        cleanupTabResources(tabId);
    }
});

chrome.debugger.onEvent.addListener((debuggeeId, method, params) => {
    const tabId = debuggeeId.tabId;
    if (!activeTabs.has(tabId)) return;

    const pendingRequest = capturedRequests[tabId];
    if (!pendingRequest) return;

    if (method === "Network.requestWillBeSent" && params.request.url.startsWith("https://workspacevideo-pa.clients6.google.com")) {
        const requestId = params.requestId;
        // Store the main URL against the request ID for later retrieval
        capturedRequests[requestId] = { url: params.request.url, tabId: tabId };

    } else if (method === "Network.responseReceived") {
        const requestId = params.requestId;
        if (capturedRequests[requestId] && capturedRequests[requestId].tabId === tabId) {
            chrome.debugger.sendCommand(
                { tabId: tabId },
                "Network.getResponseBody",
                { requestId: requestId },
                (result) => {
                    if (chrome.runtime.lastError || !result || !result.body) {
                        return; // Ignore errors or empty bodies
                    }
                    try {
                        const data = JSON.parse(result.body);
                        if (data.mediaStreamingData?.formatStreamingData?.progressiveTranscodes) {
                            const transcodes = data.mediaStreamingData.formatStreamingData.progressiveTranscodes;
                            const urls = (transcodes || []).map(t => t?.url).filter(Boolean);
                            const videoUrl = urls[urls.length - 1];
                            if (videoUrl) {
                                clearTimeout(pendingRequest.timeoutId);
                                // Attach all candidate urls to the pending request so sender can include them
                                capturedRequests[tabId] = { ...capturedRequests[tabId], urls };
                                pendingRequest.resolve(videoUrl);
                            }
                        }
                    } catch (e) { /* Ignore JSON parsing errors */ }
                }
            );
        }
    }
});

// Keep service worker alive
chrome.alarms.create('keepalive', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => {
    if (!connected) {
        connect();
        return;
    }
    // Watchdog: if no messages received for over 2 minutes while connected, restart native host
    const STALE_MS = 2 * 60 * 1000;
    if (Date.now() - lastMessageAt > STALE_MS) {
        console.warn('[Watchdog] No messages from worker recently, restarting native connection');
        try { if (port) port.disconnect(); } catch (_) {}
    }
});

// Popup communication (simplified, only status)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'status') {
        sendResponse({
            connected,
            activeTabs: activeTabs.size,
            // currentJob: currentJob // Removed currentJob as it's managed by capturePromises
        });
    }
});

// ============ Initialize ============
console.log('[Init] Drive Capture Extension v2.0 (Legacy Logic)');
connect();