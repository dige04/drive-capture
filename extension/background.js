/**
 * Drive Capture Extension - Background Service Worker
 * Merged logic for robust connection with Python worker and legacy URL capture
 */

// ============ Configuration ============
const HOST_ID = 'com.drivecapture.worker';
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]; // Exponential backoff
const CAPTURE_TIMEOUT = 20000; // Increased timeout for capture
const MAX_TABS = 5; // Max concurrent tabs for capture

// ============ State ============
let port = null;
let connected = false;
let reconnectAttempt = 0;
let reconnectTimer = null;

// Legacy capture state
let capturedRequests = {}; // Stores network requests for URL extraction
let capturePromises = {}; // To manage pending captures by fileId
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
    chrome.debugger.detach(debuggee, () => {
        if (chrome.runtime.lastError) {
            // console.warn(`[Cleanup] Detach failed for tab ${tabId}:`, chrome.runtime.lastError.message);
        }
        // Remove captured requests for this tab
        Object.keys(capturedRequests).forEach(requestId => {
            if (capturedRequests[requestId].tabId === tabId) {
                delete capturedRequests[requestId];
            }
        });
        activeTabs.delete(tabId);
        chrome.tabs.remove(tabId).catch(() => {}); // Close the tab
    });
}

// Initiates the legacy capture process for a given fileId
async function startLegacyCapture(fileId) {
    console.log(`[Legacy Capture] Starting for ${fileId}`);

    // If already capturing this fileId, return
    if (capturePromises[fileId]) {
        console.log(`[Legacy Capture] Already processing ${fileId}`);
        return;
    }

    // Clean up oldest tab if too many active
    if (activeTabs.size >= MAX_TABS) {
        const oldestTab = activeTabs.values().next().value;
        console.log(`[Legacy Capture] Closing oldest tab ${oldestTab} to make room.`);
        cleanupTabResources(oldestTab);
    }

    capturePromises[fileId] = new Promise(async (resolve, reject) => {
        let tabId;
        let timeoutId;

        try {
            // Open Drive URL
            const url = `https://drive.google.com/file/d/${fileId}/view`;
            const tab = await chrome.tabs.create({ url, active: false });
            tabId = tab.id;
            activeTabs.add(tabId);

            const debuggee = { tabId: tabId };
            await chrome.debugger.attach(debuggee, "1.3");
            await chrome.debugger.sendCommand(debuggee, "Network.enable");

            // Set a timeout for the capture
            timeoutId = setTimeout(() => {
                console.warn(`[Legacy Capture] Timeout for ${fileId} (tab ${tabId})`);
                cleanupTabResources(tabId);
                reject(new Error('Capture timed out'));
            }, CAPTURE_TIMEOUT);

            // Store resolve/reject for later use by onEvent listener
            capturedRequests[tabId] = { fileId, resolve, reject, timeoutId };

        } catch (error) {
            console.error(`[Legacy Capture] Error initiating for ${fileId}:`, error);
            if (tabId) cleanupTabResources(tabId);
            reject(error);
        }
    });

    capturePromises[fileId].then(videoUrl => {
        console.log(`[Legacy Capture] Success for ${fileId}: ${videoUrl}`);
        sendResult(fileId, videoUrl, null);
    }).catch(error => {
        console.error(`[Legacy Capture] Failed for ${fileId}:`, error.message);
        sendResult(fileId, null, error.message);
    }).finally(() => {
        // Clean up resources and promise
        const tabId = Object.keys(capturedRequests).find(id => capturedRequests[id].fileId === fileId);
        if (tabId) {
            clearTimeout(capturedRequests[tabId].timeoutId);
            cleanupTabResources(Number(tabId));
            delete capturedRequests[tabId]; // Clean up the temporary entry
        }
        delete capturePromises[fileId];
    });
}

function sendResult(fileId, url, error) {
    sendMessage({
        type: 'result',
        file_id: fileId,
        url: url,
        error: error
    });
}

// ============ Chrome Events (Legacy Logic) ============

chrome.tabs.onRemoved.addListener((tabId) => {
    if (activeTabs.has(tabId)) {
        console.log(`[Cleanup] Tab ${tabId} removed unexpectedly.`);
        cleanupTabResources(tabId);
        // If there was a pending promise for this tab, reject it
        if (capturedRequests[tabId] && capturedRequests[tabId].reject) {
            clearTimeout(capturedRequests[tabId].timeoutId);
            capturedRequests[tabId].reject(new Error('Tab closed unexpectedly'));
        }
    }
});

chrome.debugger.onEvent.addListener((debuggeeId, method, params) => {
    const tabId = debuggeeId.tabId;
    if (!activeTabs.has(tabId)) return; // Only process for tabs opened by us

    // Ensure we have a pending capture for this tab
    if (!capturedRequests[tabId] || !capturedRequests[tabId].fileId) return;

    if (method === "Network.requestWillBeSent") {
        if (params.request.url.startsWith("https://workspacevideo-pa.clients6.google.com")) {
            const requestId = params.requestId;
            capturedRequests[requestId] = {
                url: params.request.url,
                method: params.request.method,
                timestamp: params.timestamp,
                tabId: tabId
            };
        }
    } else if (method === "Network.responseReceived") {
        const requestId = params.requestId;
        if (capturedRequests[requestId] && capturedRequests[requestId].tabId === tabId) {
            chrome.debugger.sendCommand(
                { tabId: tabId },
                "Network.getResponseBody",
                { requestId: requestId },
                (result) => {
                    if (chrome.runtime.lastError) {
                        // console.warn(`[Debugger] getResponseBody failed for tab ${tabId}, req ${requestId}:`, chrome.runtime.lastError.message);
                        return;
                    }
                    capturedRequests[requestId].responseBody = result.body;
                    capturedRequests[requestId].base64Encoded = result.base64Encoded;
                    try {
                        const data = JSON.parse(result.body);
                        if (data.mediaStreamingData?.formatStreamingData?.progressiveTranscodes) {
                            const transcodes = data.mediaStreamingData.formatStreamingData.progressiveTranscodes;
                            const videoUrl = transcodes[transcodes.length - 1]?.url;
                            if (videoUrl) {
                                // Resolve the promise for this capture
                                if (capturedRequests[tabId] && capturedRequests[tabId].resolve) {
                                    capturedRequests[tabId].resolve(videoUrl);
                                }
                            }
                        }
                        // Optionally capture video title if needed by worker
                        // if (data.mediaMetadata?.title) {
                        //     capturedRequests[requestId].videoTitle = data.mediaMetadata.title;
                        // }
                    } catch (e) {
                        // console.warn(`[Debugger] Error parsing response body for tab ${tabId}, req ${requestId}:`, e);
                    }
                }
            );
        }
    }
});

// Keep service worker alive
chrome.alarms.create('keepalive', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => {
    if (!connected) connect();
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