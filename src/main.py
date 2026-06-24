#!/usr/bin/env python3
"""
WhatsApp GPT Voice Responder - PER-VOICE PERSONALITIES
Each voice (him, girl1, girl2) has its own personality
"""

import os
import time
import torch
import torch.serialization
import json
import subprocess
import random
from pathlib import Path
import argparse
from datetime import datetime
import pygame
import numpy as np
import soundfile as sf
from openai import OpenAI
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pythonosc import osc_server
from pythonosc import dispatcher
import threading

# TTS imports
from TTS.api import TTS
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
from TTS.config.shared_configs import BaseDatasetConfig

print("🎯 WHATSAPP GPT VOICE RESPONDER - PER-VOICE PERSONALITIES")
print("=" * 70)

# ==================== CONFIGURATION ====================
BASE_DIR = Path(__file__).parent.parent

RECORDINGS_DIR = BASE_DIR / "data" / "recordings"
TRANSCRIPTS_DIR = BASE_DIR / "data" / "transcripts"
BASE_OUTPUT_DIR = BASE_DIR / "data" / "output"
MODELS_DIR = BASE_DIR / "data" / "models"
WHISPER_DIR = BASE_DIR / "data" / "whisper"

PROCESSED_LOG = BASE_DIR / "data" / "processed_audio.json"
PERSONALITY_BANK_FILE = BASE_DIR / "data" / "personality_bank.json"
OSC_CONFIG_FILE = BASE_DIR / "config" / "osc_config.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WHISPER_BIN = Path("C:/Users/franc/whatsapp-voice-responder/data/whisper/whisper-bin-x64/Release/whisper-cli.exe")
WHISPER_MODEL = Path("C:/Users/franc/whatsapp-voice-responder/data/whisper/ggml-base.bin")

OSC_IP = "127.0.0.1"
OSC_PORT = 4441

VOICE_PROFILES = {
    'reader': {
        'name': 'Reader',
        'speaker_wav': MODELS_DIR / "reader.wav",
        'speed': 1.0,
        'folder': 'reader',
        'default_personality': "You read messages aloud clearly."
    },
    'him': {
        'name': 'Him',
        'speaker_wav': MODELS_DIR / "fran.wav",
        'speed': 1.0,
        'folder': 'him',
        'default_personality': "You are a sarcastic observer with dry wit. Keep responses VERY short - 1-2 sentences maximum. Be ironic and clever, never too serious."
    },
    'girl1': {
        'name': 'Girl1',
        'speaker_wav': MODELS_DIR / "camille.wav",
        'speed': 1.0,
        'folder': 'girl1',
        'default_personality': "You are a poetic woman who sees beauty in everything. Keep responses short and elegant. Be a little mysterious."
    },
    'girl2': {
        'name': 'Girl2',
        'speaker_wav': MODELS_DIR / "giovanna.wav",
        'speed': 1.0,
        'folder': 'girl2',
        'default_personality': "You are a passionate woman who feels everything intensely. Keep responses short and expressive! Use enthusiasm!"
    }
}

VOICE_MODE = 'random'
FIXED_VOICE = 'him'

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)

for voice_id, profile in VOICE_PROFILES.items():
    folder = BASE_OUTPUT_DIR / profile['folder']
    folder.mkdir(parents=True, exist_ok=True)
    profile['output_dir'] = folder

print(f"🔧 Configuration:")
print(f"  📁 Recordings: {RECORDINGS_DIR}")
print(f"  📝 Transcripts: {TRANSCRIPTS_DIR}")
print(f"  🎵 Output: {BASE_OUTPUT_DIR}")
print(f"  🎤 Voices: him, girl1, girl2")

if not WHISPER_BIN.exists():
    print(f"⚠️ whisper-cli.exe not found at {WHISPER_BIN}")

if not WHISPER_MODEL.exists():
    print(f"⚠️ Whisper model not found at {WHISPER_MODEL}")

print("\n" + "=" * 70)

# ==================== PERSONALITY BANK ====================
class PersonalityBank:
    def __init__(self, bank_file):
        self.bank_file = Path(bank_file)
        self.personalities = {}
        self.load()
    
    def load(self):
        if self.bank_file.exists():
            try:
                with open(self.bank_file, 'r', encoding='utf-8') as f:
                    self.personalities = json.load(f)
                print("✅ Loaded saved personalities")
            except Exception as e:
                print(f"⚠️ Error loading: {e}")
                self.create_defaults()
        else:
            self.create_defaults()
        self.ensure_all_voices_exist()
    
    def ensure_all_voices_exist(self):
        for voice_id, profile in VOICE_PROFILES.items():
            if voice_id not in self.personalities:
                self.personalities[voice_id] = {
                    'current': 'default',
                    'custom': {},
                    'default_prompt': profile['default_personality']
                }
                print(f"  ➕ Added missing voice: {voice_id}")
        self.save()
    
    def create_defaults(self):
        self.personalities = {}
        for voice_id, profile in VOICE_PROFILES.items():
            self.personalities[voice_id] = {
                'current': 'default',
                'custom': {},
                'default_prompt': profile['default_personality']
            }
        self.save()
        print("✅ Created default personalities")
    
    def save(self):
        try:
            with open(self.bank_file, 'w', encoding='utf-8') as f:
                json.dump(self.personalities, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving personalities: {e}")
    
    def get_prompt(self, voice_id):
        self.ensure_all_voices_exist()
        if voice_id not in self.personalities:
            voice_id = 'him'
        current = self.personalities[voice_id].get('current', 'default')
        if current != 'default' and current in self.personalities[voice_id].get('custom', {}):
            return {
                "role": "system",
                "content": self.personalities[voice_id]['custom'][current]
            }
        return {
            "role": "system",
            "content": self.personalities[voice_id].get('default_prompt', "Keep responses short.")
        }
    def get_current_info(self, voice_id):
        """Get info about current personality for a voice"""
        self.ensure_all_voices_exist()

        if voice_id not in self.personalities:
            return 'default', "Default personality"

        current = self.personalities[voice_id].get('current', 'default')
        prompt = self.get_prompt(voice_id)['content'][:100]
        return current, prompt

personality_bank = PersonalityBank(PERSONALITY_BANK_FILE)

# ==================== RANDOM VOICE SELECTION ====================
def get_random_voice():
    available_voices = []
    for voice_id, profile in VOICE_PROFILES.items():
        if profile['speaker_wav'].exists():
            available_voices.append(voice_id)
    if not available_voices:
        return 'him'
    selected = random.choice(available_voices)
    print(f"   🎲 Random voice selected: {VOICE_PROFILES[selected]['name']}")
    return selected

# ==================== AUDIO FUNCTIONS ====================
def convert_to_wav(audio_path):
    wav_path = audio_path.with_suffix('.wav')
    cmd = ['ffmpeg', '-i', str(audio_path), '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', '-y', str(wav_path)]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        return wav_path if wav_path.exists() else None
    except:
        return None

def transcribe_audio(audio_path):
    global WHISPER_BIN, WHISPER_MODEL  # <-- ADD THIS LINE
    
    print(f"   🎤 Transcribing...")
    print(f"   🔍 WHISPER_BIN: {WHISPER_BIN}")
    print(f"   🔍 Exists: {WHISPER_BIN.exists()}")
    
    wav_path = convert_to_wav(audio_path)
    if not wav_path:
        return None
    
    if not WHISPER_BIN.exists() or not WHISPER_MODEL.exists():
        print("   ❌ Whisper not installed!")
        return None
    
    cmd = [str(WHISPER_BIN), "-m", str(WHISPER_MODEL), "-f", str(wav_path), "-l", "en", "-nt"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        wav_path.unlink()
        if result.returncode != 0:
            return None
        transcription = result.stdout.strip()
        if not transcription:
            return None
        print(f"   ✅ Transcribed: {transcription[:100]}...")
        return transcription
    except:
        if wav_path.exists():
            wav_path.unlink()
        return None

def play_audio(file_path):
    try:
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception as e:
        print(f"❌ Audio playback error: {e}")

# ==================== TTS SETUP ====================
import TTS.tts.models.xtts as xtts_module

original_load_audio = xtts_module.load_audio

def patched_load_audio(audiopath, sampling_rate):
    try:
        audio, sr = sf.read(audiopath)
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)
        if sr != sampling_rate:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=sampling_rate)
        audio_tensor = torch.FloatTensor(audio).unsqueeze(0)
        return audio_tensor
    except:
        return original_load_audio(audiopath, sampling_rate)

xtts_module.load_audio = patched_load_audio

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🚀 Using device: {device.upper()}")

print("📥 Loading XTTSv2...")
try:
    with torch.serialization.safe_globals([XttsConfig, XttsAudioConfig, BaseDatasetConfig, XttsArgs]):
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    print("✅ XTTSv2 loaded!")
except Exception as e:
    print(f"⚠️ TTS not loaded: {e}")
    tts = None

# ==================== OPENAI SETUP ====================
if not OPENAI_API_KEY or OPENAI_API_KEY == "your-api-key-here":
    print("❌ OPENAI_API_KEY not set or still placeholder!")
    print("   Please add your actual API key to .env file")
    client = None
else:
    client = OpenAI(api_key=OPENAI_API_KEY)
    print("✅ OpenAI client initialized")

# ==================== GPT RESPONSE ====================
def get_gpt_response(user_message, conversation_history, voice_id):
    if not client:
        return "OpenAI not configured. Please set OPENAI_API_KEY.", conversation_history, 0
    
    system_prompt = personality_bank.get_prompt(voice_id)
    
    if not conversation_history:
        conversation_history = [system_prompt]
    elif conversation_history[0]["role"] != "system":
        conversation_history.insert(0, system_prompt)
    else:
        conversation_history[0] = system_prompt
    
    conversation_history.append({"role": "user", "content": user_message})
    
    try:
        start_time = time.time()
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=conversation_history,
            max_tokens=50,
            temperature=0.9
        )
        gpt_time = time.time() - start_time
        ai_response = response.choices[0].message.content
        conversation_history.append({"role": "assistant", "content": ai_response})
        
        if len(conversation_history) > 21:
            conversation_history = conversation_history[:1] + conversation_history[-20:]
        
        return ai_response, conversation_history, gpt_time
    except Exception as e:
        print(f"❌ GPT Error: {e}")
        return None, conversation_history, 0

# ==================== VOICE GENERATION ====================
def generate_voice(text, voice_id):
    if not tts:
        print("   ❌ TTS not available")
        return None, 0
    
    voice_profile = VOICE_PROFILES.get(voice_id, VOICE_PROFILES['him'])
    
    if not voice_profile['speaker_wav'].exists():
        print(f"  ❌ Speaker file missing for {voice_profile['name']}")
        return None, 0
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_filename = f"{voice_profile['name']}_{timestamp}.wav"
    audio_path = voice_profile['output_dir'] / audio_filename
    
    print(f"\n🎤 Generating voice using {voice_profile['name']}")
    
    try:
        tts_start = time.time()
        tts.tts_to_file(
            text=text,
            speaker_wav=str(voice_profile['speaker_wav']),
            language="en",
            file_path=str(audio_path),
            speed=voice_profile['speed']
        )
        tts_time = time.time() - tts_start
        print(f"✅ Voice generated: {audio_filename}")
        return str(audio_path), tts_time
    except Exception as e:
        print(f"❌ TTS error: {e}")
        return None, 0

# ==================== PROCESSED FILES ====================
def load_processed():
    if PROCESSED_LOG.exists():
        try:
            with open(PROCESSED_LOG, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_processed(filename):
    processed = load_processed()
    processed.add(str(filename))
    with open(PROCESSED_LOG, 'w') as f:
        json.dump(list(processed), f)

# ==================== AUDIO HANDLER ====================
class AudioHandler(FileSystemEventHandler):
    def __init__(self, auto_play=True, process_existing=True):
        self.auto_play = auto_play
        self.process_existing = process_existing
        self.processed = load_processed()
        
        personality_bank.ensure_all_voices_exist()
        
        self.conversation_histories = {
            'reader': [],
            'him': [],
            'girl1': [],
            'girl2': []
        }
        
        self.stats = {
            'files_processed': 0,
            'total_transcribe_time': 0,
            'total_gpt_time': 0,
            'total_tts_time': 0,
            'voice_counts': {'reader': 0, 'him': 0, 'girl1': 0, 'girl2': 0}
        }
        
        print(f"\n📋 Already processed: {len(self.processed)} files")
        
        if process_existing:
            self._process_existing()
    
    def _process_existing(self):
        existing_audio = list(RECORDINGS_DIR.glob("*.ogg"))
        if existing_audio:
            print(f"\n📋 Found {len(existing_audio)} existing audio file(s)")
            for file in existing_audio:
                if str(file) not in self.processed:
                    self._process_audio(file)
        
        existing_text = list(TRANSCRIPTS_DIR.glob("*.txt"))
        if existing_text:
            print(f"\n📋 Found {len(existing_text)} existing text file(s)")
            for file in existing_text:
                if str(file) not in self.processed:
                    self._process_text_file(file)
    
    def _process_audio(self, audio_path):
        print(f"\n{'='*70}")
        print(f"📁 Processing AUDIO: {audio_path.name}")
        print(f"{'='*70}")
        
        if VOICE_MODE == 'random':
            voice_id = get_random_voice()
        else:
            voice_id = FIXED_VOICE
        
        print(f"🎭 Voice: {VOICE_PROFILES[voice_id]['name']}")
        
        current_personality, _ = personality_bank.get_current_info(voice_id)
        print(f"🎭 Personality: {current_personality}")
        
        transcribe_start = time.time()
        transcription = transcribe_audio(audio_path)
        transcribe_time = time.time() - transcribe_start
        
        if not transcription:
            print("   ❌ Transcription failed")
            return
        
        print(f"   📝 Text: {transcription}")
        print(f"   ⏱️  Transcription: {transcribe_time:.2f}s")
        print(f"   🤖 Getting GPT response...")
        ai_response, updated_history, gpt_time = get_gpt_response(
            transcription, 
            self.conversation_histories[voice_id],
            voice_id
        )
        self.conversation_histories[voice_id] = updated_history
        
        if not ai_response:
            print("   ❌ GPT failed")
            return
        
        print(f"   🤖 AI: {ai_response}")
        print(f"   ⏱️  GPT: {gpt_time:.2f}s")
        
        output_file, tts_time = generate_voice(ai_response, voice_id)
        
        if output_file:
            self.stats['files_processed'] += 1
            self.stats['total_transcribe_time'] += transcribe_time
            self.stats['total_gpt_time'] += gpt_time
            self.stats['total_tts_time'] += tts_time
            self.stats['voice_counts'][voice_id] += 1
            self.processed.add(str(audio_path))
            save_processed(audio_path)
            
            if self.auto_play:
                print("   🔊 Playing response...")
                play_audio(output_file)
            
            if self.stats['files_processed'] > 0:
                print(f"\n📊 Stats: {self.stats['files_processed']} files")
                print(f"   Voice counts: Him: {self.stats['voice_counts']['him']}, "
                      f"Girl1: {self.stats['voice_counts']['girl1']}, "
                      f"Girl2: {self.stats['voice_counts']['girl2']}")
    
    def _process_text_file(self, text_file_path):
        try:
            with open(text_file_path, 'r', encoding='utf-8') as f:
                text_data = json.load(f)
            
            user_message = text_data.get('text', '')
            if not user_message:
                print(f"⚠️ Empty text file: {text_file_path.name}")
                text_file_path.unlink()
                return
            
            print(f"\n{'='*70}")
            print(f"📝 TEXT MESSAGE RECEIVED")
            print(f"   From: {text_data.get('from_name', text_data.get('from', 'unknown'))}")
            print(f"   Message: {user_message}")
            print(f"{'='*70}")
            
            reader_voice_id = 'reader'
            if reader_voice_id not in VOICE_PROFILES or not VOICE_PROFILES[reader_voice_id]['speaker_wav'].exists():
                print(f"   ⚠️ Reader voice not found, using Him for cloning")
                reader_voice_id = 'him'
            
            print(f"\n🎤 Reading message with {VOICE_PROFILES[reader_voice_id]['name']} voice...")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            clone_filename = f"read_{VOICE_PROFILES[reader_voice_id]['name']}_{timestamp}.wav"
            clone_path = VOICE_PROFILES[reader_voice_id]['output_dir'] / clone_filename
            
            try:
                if tts:
                    tts.tts_to_file(
                        text=user_message,
                        speaker_wav=str(VOICE_PROFILES[reader_voice_id]['speaker_wav']),
                        language="en",
                        file_path=str(clone_path),
                        speed=VOICE_PROFILES[reader_voice_id]['speed']
                    )
                    print(f"   ✅ Message read: {clone_filename}")
                    
                    if self.auto_play:
                        print("   🔊 Reading incoming message...")
                        play_audio(str(clone_path))
            except Exception as e:
                print(f"   ❌ Failed to read message: {e}")
            
            if VOICE_MODE == 'random':
                gpt_voice_id = get_random_voice()
            else:
                gpt_voice_id = FIXED_VOICE
            
            print(f"\n🤖 Generating GPT response using {VOICE_PROFILES[gpt_voice_id]['name']}...")
            
            ai_response, updated_history, gpt_time = get_gpt_response(
                user_message, 
                self.conversation_histories[gpt_voice_id],
                gpt_voice_id
            )
            self.conversation_histories[gpt_voice_id] = updated_history
            
            if not ai_response:
                print("   ❌ GPT failed")
                text_file_path.unlink()
                return
            
            print(f"   🤖 AI: {ai_response}")
            print(f"   ⏱️  GPT: {gpt_time:.2f}s")
            
            output_file, tts_time = generate_voice(ai_response, gpt_voice_id)
            
            if output_file:
                self.stats['files_processed'] += 1
                self.stats['total_gpt_time'] += gpt_time
                self.stats['total_tts_time'] += tts_time
                self.stats['voice_counts'][gpt_voice_id] += 1
                
                if self.auto_play:
                    print("   🔊 Playing GPT response...")
                    play_audio(output_file)
                
                if self.stats['files_processed'] > 0:
                    print(f"\n📊 Stats: {self.stats['files_processed']} messages")
                    print(f"   Voice counts: Him: {self.stats['voice_counts']['him']}, "
                          f"Girl1: {self.stats['voice_counts']['girl1']}, "
                          f"Girl2: {self.stats['voice_counts']['girl2']}")
            
            text_file_path.unlink()
            
        except Exception as e:
            print(f"❌ Error processing text file: {e}")
            try:
                text_file_path.unlink()
            except:
                pass
    
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        
        if path.suffix.lower() == '.ogg' and str(path) not in self.processed:
            time.sleep(0.5)
            self._process_audio(path)
        elif path.suffix.lower() == '.txt' and str(path) not in self.processed:
            time.sleep(0.1)
            self._process_text_file(path)

# ==================== OSC HANDLERS ====================
def start_osc_server():
    disp = dispatcher.Dispatcher()
    
    def osc_set_custom_prompt(address, *args):
        parts = address.split('/')
        if len(parts) >= 4 and len(args) >= 1:
            voice_id = parts[2]
            prompt_name = parts[3]
            prompt_text = args[0]
            
            if voice_id not in VOICE_PROFILES:
                print(f"\n❌ Unknown voice: {voice_id}")
                return
            
            success, message = personality_bank.set_custom_prompt(voice_id, prompt_name, prompt_text)
            print(f"\n📝 OSC: {message}")
    
    def osc_set_personality(address, *args):
        parts = address.split('/')
        if len(parts) >= 4:
            voice_id = parts[2]
            personality_name = parts[3]
            
            if voice_id not in VOICE_PROFILES:
                print(f"\n❌ Unknown voice: {voice_id}")
                return
            
            success, message = personality_bank.set_personality(voice_id, personality_name)
            print(f"\n🎭 OSC: {message}")
    
    def osc_get_status(address, *args):
        print(f"\n{'='*60}")
        print("🎭 CURRENT PERSONALITY STATUS")
        print(f"{'='*60}")
        
        personality_bank.ensure_all_voices_exist()
        
        for voice_id, profile in VOICE_PROFILES.items():
            try:
                current, prompt_preview = personality_bank.get_current_info(voice_id)
                print(f"\n{profile['name']} ({voice_id}):")
                print(f"  Personality: {current}")
            except Exception as e:
                print(f"\n{profile['name']} ({voice_id}):")
                print(f"  Error: {e}")
        
        print(f"\n🎲 Voice Mode: {VOICE_MODE.upper()}")
        if VOICE_MODE == 'fixed':
            print(f"  Fixed voice: {VOICE_PROFILES[FIXED_VOICE]['name']}")
        print(f"{'='*60}")
    
    def osc_set_voice_mode(address, *args):
        global VOICE_MODE, FIXED_VOICE
        if len(args) >= 1:
            mode = args[0].lower()
            if mode == 'random':
                VOICE_MODE = 'random'
                print(f"\n🎲 Voice mode set to: RANDOM")
            elif mode == 'fixed':
                VOICE_MODE = 'fixed'
                print(f"\n🎤 Voice mode set to: FIXED")
                if len(args) >= 2:
                    voice = args[1].lower()
                    if voice in VOICE_PROFILES:
                        FIXED_VOICE = voice
                        print(f"   Fixed voice: {VOICE_PROFILES[voice]['name']}")
            else:
                print(f"\n❌ Unknown mode: {mode}")
    
    def osc_ping(address, *args):
        print("🏓 OSC pong")
    
    disp.map("/custom/*/*", osc_set_custom_prompt)
    disp.map("/personality/*/*", osc_set_personality)
    disp.map("/status", osc_get_status)
    disp.map("/voice/mode", osc_set_voice_mode)
    disp.map("/ping", osc_ping)
    
    server = osc_server.ThreadingOSCUDPServer((OSC_IP, OSC_PORT), disp)
    print(f"🌐 OSC server listening on {OSC_IP}:{OSC_PORT}")
    server.serve_forever()

# ==================== MAIN ====================
def main():
    parser = argparse.ArgumentParser(description='WhatsApp GPT Voice Responder')
    parser.add_argument('--no-play', action='store_true', help='Disable auto-playback')
    parser.add_argument('--no-existing', action='store_true', help='Skip existing files')
    parser.add_argument('--file', help='Process a single audio file')
    parser.add_argument('--text', help='Direct text input (bypass audio)')
    parser.add_argument('--osc-port', type=int, help='OSC port (default: 4441)')
    parser.add_argument('--voice-mode', choices=['random', 'fixed'], default='random', 
                       help='Voice selection mode')
    parser.add_argument('--fixed-voice', choices=['him', 'girl1', 'girl2'], 
                       default='him', help='Fixed voice to use')
    
    args = parser.parse_args()
    
    global VOICE_MODE, FIXED_VOICE, OSC_PORT
    VOICE_MODE = args.voice_mode
    if args.voice_mode == 'fixed':
        FIXED_VOICE = args.fixed_voice
    
    if args.osc_port:
        OSC_PORT = args.osc_port
    
    osc_thread = threading.Thread(target=start_osc_server, daemon=True)
    osc_thread.start()
    time.sleep(1)
    
    if args.text:
        print(f"📝 Direct text: {args.text[:100]}...")
        voice_id = get_random_voice() if VOICE_MODE == 'random' else FIXED_VOICE
        ai_response, _, _ = get_gpt_response(args.text, [], voice_id)
        if ai_response:
            print(f"🤖 AI: {ai_response}")
            output_file, _ = generate_voice(ai_response, voice_id)
            if output_file and not args.no_play:
                play_audio(output_file)
        return
    
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return
        handler = AudioHandler(auto_play=not args.no_play, process_existing=False)
        handler._process_audio(file_path)
        return
    
    print("\n" + "="*70)
    print("🎯 WHATSAPP GPT VOICE RESPONDER - RUNNING".center(70))
    print("="*70)
    print(f"📁 Watching for AUDIO: {RECORDINGS_DIR}")
    print(f"📁 Watching for TEXT: {TRANSCRIPTS_DIR}")
    print(f"🎛️ OSC Control: {OSC_IP}:{OSC_PORT}")
    print(f"🎲 Voice mode: {VOICE_MODE.upper()}")
    if VOICE_MODE == 'fixed':
        print(f"   Fixed voice: {VOICE_PROFILES[FIXED_VOICE]['name']}")
    print("="*70 + "\n")
    
    handler = AudioHandler(
        auto_play=not args.no_play,
        process_existing=not args.no_existing
    )
    
    observer = Observer()
    observer.schedule(handler, str(RECORDINGS_DIR), recursive=False)
    observer.schedule(handler, str(TRANSCRIPTS_DIR), recursive=False)
    observer.start()
    
    print(f"👂 Monitoring for WhatsApp messages...")
    print("   🎤 Audio messages will be transcribed via Whisper")
    print("   📝 Text messages will go directly to GPT")
    print("📌 Press Ctrl+C to stop\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n\n👋 Stopped")
    
    observer.join()

if __name__ == "__main__":
    main()