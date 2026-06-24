// whatsapp_audio_listener.js

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');
const osc = require('osc');

// OSC configuration
const oscPort = new osc.UDPPort({
    remoteAddress: "127.0.0.1",
    remotePort: 5120
});

oscPort.open();

oscPort.on("ready", () => {
    console.log(`✅ OSC client ready - sending to 127.0.0.1:5120`);
});

// ==================== FIXED PATHS ====================
// Save files where Python can see them
const recordingsDir = path.join(__dirname, '..', 'data', 'recordings');
const transcriptsDir = path.join(__dirname, '..', 'data', 'transcripts');

// Create directories if they don't exist
if (!fs.existsSync(recordingsDir)) {
    fs.mkdirSync(recordingsDir, { recursive: true });
    console.log(`📁 Created: ${recordingsDir}`);
}

if (!fs.existsSync(transcriptsDir)) {
    fs.mkdirSync(transcriptsDir, { recursive: true });
    console.log(`📁 Created: ${transcriptsDir}`);
}
// =====================================================

// Helper function to get sender identifier
async function getSenderIdentifier(msg) {
    try {
        const contact = await msg.getContact();
        
        if (contact.number) {
            const cleanNumber = contact.number.replace(/[^0-9+]/g, '');
            return { identifier: cleanNumber, type: 'number', original: contact.number };
        } else if (contact.name && contact.name !== 'Unknown') {
            const cleanName = contact.name.replace(/[^a-zA-Z0-9]/g, '_');
            return { identifier: cleanName, type: 'name', original: contact.name };
        } else if (contact.pushname) {
            const cleanPushname = contact.pushname.replace(/[^a-zA-Z0-9]/g, '_');
            return { identifier: cleanPushname, type: 'pushname', original: contact.pushname };
        } else {
            const cleanId = msg.from.replace(/[^a-zA-Z0-9]/g, '_');
            return { identifier: cleanId, type: 'id', original: msg.from };
        }
    } catch (error) {
        console.error(`Error getting contact info: ${error}`);
        const cleanId = msg.from.replace(/[^a-zA-Z0-9]/g, '_');
        return { identifier: cleanId, type: 'id', original: msg.from };
    }
}

// WhatsApp Client with Session Persistence
const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: './sessions',
        clientId: 'whatsapp-voice-bot'
    }),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// Display QR code
client.on('qr', qr => {
    console.log('📱 Scan this QR code with your WhatsApp phone:');
    qrcode.generate(qr, { small: true });
    console.log('(You only need to do this once - session will be saved!)');
});

// Client ready
client.on('ready', () => {
    console.log('✅ WhatsApp client ready!');
    console.log('📁 Session saved - you won\'t need to scan QR again!');
    console.log(`📁 Recordings: ${recordingsDir}`);
    console.log(`📁 Transcripts: ${transcriptsDir}`);
    console.log('Waiting for audio messages or text messages...');
});

// Handle incoming messages
client.on('message', async msg => {
    // Check for text messages
    if (msg.type === 'chat' && msg.body) {
        const trimmedMsg = msg.body.trim();
        
        // Check if message is a single number (OSC trigger)
        if (/^\d+$/.test(trimmedMsg)) {
            const value = parseInt(trimmedMsg);
            console.log(`[OSC] Received number: ${value} from ${msg.from}`);
            
            oscPort.send({
                address: "/whatsapp/number",
                args: [{ type: "i", value: value }]
            });
            console.log(`[OSC] Sent: /whatsapp/number ${value}`);
            return; // Don't process as text
        }
        
        // Handle regular text messages
        if (trimmedMsg.toLowerCase() !== 'ping') {
            console.log(`[TEXT] Received from ${msg.from}: ${trimmedMsg.substring(0, 50)}...`);
            
            const senderInfo = await getSenderIdentifier(msg);
            const timestamp = Date.now();
            
            const textFileName = `whatsapp_text_${senderInfo.identifier}_${timestamp}.txt`;
            const textFilePath = path.join(transcriptsDir, textFileName);
            
            const textData = {
                source: 'whatsapp_text',
                from_id: msg.from,
                from_name: senderInfo.original,
                from_type: senderInfo.type,
                timestamp: timestamp,
                timestamp_readable: new Date(timestamp).toISOString(),
                text: trimmedMsg
            };
            
            fs.writeFileSync(textFilePath, JSON.stringify(textData, null, 2));
            console.log(`[TEXT] Saved to transcripts: ${textFileName}`);
            console.log(`[TEXT] Sender: ${senderInfo.original} (${senderInfo.type})`);
        }
    }
    
    // Handle audio messages
    if (msg.hasMedia) {
        try {
            const media = await msg.downloadMedia();
            if (media.mimetype && media.mimetype.startsWith('audio/')) {
                const senderInfo = await getSenderIdentifier(msg);
                const timestamp = Date.now();
                const filename = `${senderInfo.identifier}_${timestamp}.ogg`;
                const filepath = path.join(recordingsDir, filename);
                const buffer = Buffer.from(media.data, 'base64');
                fs.writeFileSync(filepath, buffer);
                console.log(`[AUDIO] Saved: ${filename} from ${senderInfo.original}`);
                console.log(`[AUDIO] Size: ${(buffer.length / 1024).toFixed(1)} KB`);
                
                // Send OSC notification to Python
                oscPort.send({
                    address: "/whatsapp/audio",
                    args: [{ type: "s", value: filename }]
                });
                console.log(`[AUDIO] Notified Python via OSC`);
            }
        } catch (error) {
            console.error(`Error downloading audio: ${error}`);
        }
    }
});

// Handle OSC errors
oscPort.on("error", (err) => {
    console.error("OSC Error:", err);
});

// Start client
client.initialize();

// Graceful shutdown
process.on('SIGINT', () => {
    console.log('\nClosing connections...');
    oscPort.close();
    client.destroy();
    process.exit();
});