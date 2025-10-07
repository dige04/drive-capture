// Popup script for Drive Capture v2

document.addEventListener('DOMContentLoaded', async () => {
    // Get status from background
    const response = await chrome.runtime.sendMessage({ type: 'status' });
    
    // Update UI
    const statusEl = document.getElementById('status');
    const tabsEl = document.getElementById('tabs');
    const jobEl = document.getElementById('job');
    const extIdEl = document.getElementById('extId');
    const testBtn = document.getElementById('test');
    
    // Show extension ID
    extIdEl.textContent = chrome.runtime.id;
    
    // Update connection status
    if (response.connected) {
        statusEl.className = 'status connected';
        statusEl.textContent = '✅ Connected to worker';
        testBtn.disabled = false;
    } else {
        statusEl.className = 'status disconnected';
        statusEl.textContent = '❌ Worker not connected';
        testBtn.disabled = true;
    }
    
    // Update stats
    tabsEl.textContent = response.activeTabs || 0;
    jobEl.textContent = response.currentJob || 'None';
    
    // Test button
    testBtn.addEventListener('click', () => {
        testBtn.disabled = true;
        testBtn.textContent = 'Testing...';
        
        // Send test message
        chrome.runtime.sendMessage({ type: 'test' });
        
        setTimeout(() => {
            testBtn.disabled = false;
            testBtn.textContent = 'Test sent!';
            
            setTimeout(() => {
                testBtn.textContent = 'Test Connection';
            }, 2000);
        }, 1000);
    });
});
