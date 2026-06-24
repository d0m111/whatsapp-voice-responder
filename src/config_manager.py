

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from dotenv import load_dotenv
"""
Configuration Manager - Centralizes all configuration for the WhatsApp Voice Responder
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from dotenv import load_dotenv


@dataclass
class PathsConfig:
    """All file paths used by the application"""
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    recordings_dir: Optional[Path] = None
    transcripts_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    models_dir: Optional[Path] = None
    whisper_dir: Optional[Path] = None
    processed_log: Optional[Path] = None
    personality_bank: Optional[Path] = None
    osc_config: Optional[Path] = None
    whisper_bin: Optional[Path] = None
    whisper_model: Optional[Path] = None
    
    def __post_init__(self):
        if self.base_dir:
            self.recordings_dir = self.base_dir / "data" / "recordings"
            self.transcripts_dir = self.base_dir / "data" / "transcripts"
            self.output_dir = self.base_dir / "data" / "output"
            self.models_dir = self.base_dir / "data" / "models"
            self.whisper_dir = self.base_dir / "data" / "whisper"
            self.processed_log = self.base_dir / "data" / "processed_audio.json"
            self.personality_bank = self.base_dir / "data" / "personality_bank.json"
            self.osc_config = self.base_dir / "config" / "osc_config.json"
            self.whisper_bin = self.whisper_dir / "whisper-cli.exe"
            self.whisper_model = self.whisper_dir / "ggml-base.bin"


@dataclass
class VoiceProfile:
    """Configuration for a single voice"""
    name: str
    speaker_wav: Path
    speed: float = 1.0
    folder: str = ""
    default_personality: str = ""
    output_dir: Optional[Path] = None


@dataclass
class VoicesConfig:
    """All voice configurations"""
    profiles: Dict[str, VoiceProfile] = field(default_factory=dict)
    mode: str = "random"  # "random" or "fixed"
    fixed_voice: str = "him"
    
    def get_voice(self, voice_id: str) -> VoiceProfile:
        if voice_id in self.profiles:
            return self.profiles[voice_id]
        return self.profiles.get('him', VoiceProfile(name="Him", speaker_wav=Path()))
    
    def get_available_voices(self) -> list:
        return [vid for vid, v in self.profiles.items() if v.speaker_wav and v.speaker_wav.exists()]


@dataclass
class OSCConfig:
    ip: str = "127.0.0.1"
    port: int = 4441


@dataclass
class OpenAIConfig:
    model: str = "gpt-3.5-turbo"
    max_tokens: int = 50
    temperature: float = 0.9
    api_key: Optional[str] = None


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    playback_sample_rate: int = 22050
    channels: int = 1


@dataclass
class TTSConfig:
    model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    language: str = "en"


class Config:
    def __init__(self):
        load_dotenv()
        self.paths = PathsConfig()
        self.osc = OSCConfig()
        self.openai = OpenAIConfig()
        self.audio = AudioConfig()
        self.tts = TTSConfig()
        self.voices = self._create_voice_profiles()
        self.openai.api_key = os.getenv("OPENAI_API_KEY")
    
    def _create_voice_profiles(self) -> VoicesConfig:
        models_dir = self.paths.models_dir
        
        profiles = {
            'reader': VoiceProfile(
                name="Reader",
                speaker_wav=models_dir / "reader.wav",
                speed=1.0,
                folder="reader",
                default_personality="You read messages aloud clearly."
            ),
            'him': VoiceProfile(
                name="Him",
                speaker_wav=models_dir / "fran.wav",
                speed=1.0,
                folder="him",
                default_personality="You are a sarcastic observer with dry wit. Keep responses VERY short - 1-2 sentences maximum. Be ironic and clever, never too serious."
            ),
            'girl1': VoiceProfile(
                name="Girl1",
                speaker_wav=models_dir / "camille.wav",
                speed=1.0,
                folder="girl1",
                default_personality="You are a poetic woman who sees beauty in everything. Keep responses short and elegant. Be a little mysterious."
            ),
            'girl2': VoiceProfile(
                name="Girl2",
                speaker_wav=models_dir / "giovanna.wav",
                speed=1.0,
                folder="girl2",
                default_personality="You are a passionate woman who feels everything intensely. Keep responses short and expressive! Use enthusiasm!"
            )
        }
        
        for voice_id, profile in profiles.items():
            profile.output_dir = self.paths.output_dir / profile.folder
        
        return VoicesConfig(
            profiles=profiles,
            mode="random",
            fixed_voice="him"
        )
    
    def create_directories(self):
        directories = [
            self.paths.recordings_dir,
            self.paths.transcripts_dir,
            self.paths.output_dir,
            self.paths.models_dir,
            self.paths.whisper_dir,
        ]
        for directory in directories:
            if directory:
                directory.mkdir(parents=True, exist_ok=True)
        
        for profile in self.voices.profiles.values():
            if profile.output_dir:
                profile.output_dir.mkdir(parents=True, exist_ok=True)
    
    def verify(self) -> bool:
        all_ok = True
        
        if not self.paths.whisper_bin or not self.paths.whisper_bin.exists():
            print(f"⚠️ whisper-cli.exe not found at {self.paths.whisper_bin}")
            print("   Please install whisper.cpp first!")
            all_ok = False
        
        if not self.paths.whisper_model or not self.paths.whisper_model.exists():
            print(f"⚠️ Whisper model not found at {self.paths.whisper_model}")
            print("   Please download: ggml-base.bin")
            all_ok = False
        
        if not self.openai.api_key:
            print("⚠️ OPENAI_API_KEY not set in .env file")
            all_ok = False
        
        for voice_id, profile in self.voices.profiles.items():
            if not profile.speaker_wav.exists():
                print(f"⚠️ Voice sample not found: {profile.speaker_wav}")
                print(f"   Please add {voice_id}.wav to {self.paths.models_dir}")
        
        return all_ok
    
    def print_status(self):
        print("\n" + "=" * 60)
        print("🔧 CONFIGURATION STATUS")
        print("=" * 60)
        print("\n📁 Paths:")
        print(f"  Recordings: {self.paths.recordings_dir}")
        print(f"  Transcripts: {self.paths.transcripts_dir}")
        print(f"  Output: {self.paths.output_dir}")
        print(f"  Models: {self.paths.models_dir}")
        print(f"  Whisper: {self.paths.whisper_dir}")
        print("\n🎤 Voices:")
        for voice_id, profile in self.voices.profiles.items():
            exists = "✅" if profile.speaker_wav.exists() else "❌"
            print(f"  {exists} {profile.name} ({voice_id})")
        print(f"\n🎲 Voice Mode: {self.voices.mode.upper()}")
        if self.voices.mode == 'fixed':
            print(f"  Fixed voice: {self.voices.fixed_voice}")
        print(f"\n🌐 OSC: {self.osc.ip}:{self.osc.port}")
        print(f"\n🤖 OpenAI: {self.openai.model}")
        print(f"  API Key: {'✅ Set' if self.openai.api_key else '❌ Missing'}")
        whisper_ok = self.paths.whisper_bin and self.paths.whisper_bin.exists()
        model_ok = self.paths.whisper_model and self.paths.whisper_model.exists()
        print(f"\n🎤 Whisper: {'✅' if whisper_ok else '❌'} Binary")
        print(f"  Model: {'✅' if model_ok else '❌'}")
        print("=" * 60 + "\n")
    
    def to_dict(self) -> dict:
        return {
            'paths': {
                'recordings_dir': str(self.paths.recordings_dir),
                'transcripts_dir': str(self.paths.transcripts_dir),
                'output_dir': str(self.paths.output_dir),
                'models_dir': str(self.paths.models_dir),
                'whisper_dir': str(self.paths.whisper_dir),
            },
            'osc': {
                'ip': self.osc.ip,
                'port': self.osc.port,
            },
            'openai': {
                'model': self.openai.model,
                'max_tokens': self.openai.max_tokens,
                'temperature': self.openai.temperature,
            },
            'voice_mode': {
                'mode': self.voices.mode,
                'fixed_voice': self.voices.fixed_voice,
            }
        }


config = Config()