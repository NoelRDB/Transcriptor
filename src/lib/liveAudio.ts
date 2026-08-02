import type { LiveAudioSource, LiveLatency } from "../types";

const TARGET_SAMPLE_RATE = 16_000;
const SPEECH_RMS = 0.012;
const LATENCY_PROFILES: Record<LiveLatency, { minSeconds: number; maxSeconds: number; silenceSeconds: number; bufferSize: 2048 | 4096 }> = {
  ultra: { minSeconds: 0.58, maxSeconds: 1.05, silenceSeconds: 0.18, bufferSize: 2048 },
  balanced: { minSeconds: 0.78, maxSeconds: 1.45, silenceSeconds: 0.24, bufferSize: 2048 },
  stable: { minSeconds: 1.1, maxSeconds: 2.15, silenceSeconds: 0.32, bufferSize: 4096 },
};

export type LiveAudioChunkHandler = (pcmBase64: string) => void;
export type AudioLevelHandler = (level: number) => void;
export type AudioDurationHandler = (durationMs: number) => void;
export type AudioCaptureMode = "speech" | "recording";

export class LiveAudioCapture {
  private context: AudioContext | null = null;
  private streams: MediaStream[] = [];
  private sources: MediaStreamAudioSourceNode[] = [];
  private processor: ScriptProcessorNode | null = null;
  private silentGain: GainNode | null = null;
  private chunks: Int16Array[] = [];
  private sampleCount = 0;
  private silenceSamples = 0;
  private heardSpeech = false;
  private totalSampleCount = 0;
  private paused = false;

  constructor(
    private readonly onChunk: LiveAudioChunkHandler,
    private readonly onLevel: AudioLevelHandler,
    private readonly latency: LiveLatency = "balanced",
    private readonly onDuration: AudioDurationHandler = () => undefined,
    private readonly mode: AudioCaptureMode = "speech",
  ) {}

  async start(audioSource: LiveAudioSource = "microphone"): Promise<void> {
    if (!navigator.mediaDevices) throw new Error("Este sistema no ofrece captura de audio.");
    const requestedStreams: MediaStream[] = [];
    if (audioSource === "microphone" || audioSource === "mixed") {
      if (!navigator.mediaDevices.getUserMedia) throw new Error("Este sistema no ofrece acceso al micrófono.");
      requestedStreams.push(await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      }));
    }
    if (audioSource === "system" || audioSource === "mixed") {
      if (!navigator.mediaDevices.getDisplayMedia) throw new Error("WebView2 no ofrece captura del sonido del sistema.");
      const display = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
      if (!display.getAudioTracks().length) {
        display.getTracks().forEach((track) => track.stop());
        requestedStreams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
        throw new Error("La fuente compartida no incluye audio. Activa «Compartir audio del sistema».");
      }
      requestedStreams.push(display);
    }
    this.streams = requestedStreams;
    this.context = new AudioContext({ latencyHint: "interactive" });
    await this.context.resume();
    this.totalSampleCount = 0;
    this.paused = false;
    this.sources = this.streams.map((stream) => this.context!.createMediaStreamSource(stream));
    // ScriptProcessor has the broadest WebView2 support. Worklet migration is
    // isolated to this class when all supported platforms expose AudioWorklet.
    const latencyProfile = LATENCY_PROFILES[this.latency];
    this.processor = this.context.createScriptProcessor(latencyProfile.bufferSize, 1, 1);
    this.silentGain = this.context.createGain();
    this.silentGain.gain.value = 0;
    this.processor.onaudioprocess = (event) => {
      if (this.paused) return;
      const input = event.inputBuffer.getChannelData(0);
      const rms = Math.sqrt(input.reduce((sum, sample) => sum + sample * sample, 0) / input.length);
      this.onLevel(Math.min(1, rms * 7));
      const downsampled = downsample(input, this.context?.sampleRate ?? TARGET_SAMPLE_RATE, TARGET_SAMPLE_RATE);
      const pcm = floatToInt16(downsampled);
      this.chunks.push(pcm);
      this.sampleCount += pcm.length;
      this.totalSampleCount += pcm.length;
      this.onDuration(Math.round(this.totalSampleCount / TARGET_SAMPLE_RATE * 1000));
      if (this.mode === "recording") {
        if (this.sampleCount >= TARGET_SAMPLE_RATE) this.flush();
        return;
      }
      if (rms >= SPEECH_RMS) {
        this.heardSpeech = true;
        this.silenceSamples = 0;
      } else if (this.heardSpeech) {
        this.silenceSamples += pcm.length;
      }
      const enoughSpeech = this.heardSpeech && this.sampleCount >= TARGET_SAMPLE_RATE * latencyProfile.minSeconds;
      const phraseEnded = enoughSpeech && this.silenceSamples >= TARGET_SAMPLE_RATE * latencyProfile.silenceSeconds;
      const reachedMaximum = this.sampleCount >= TARGET_SAMPLE_RATE * latencyProfile.maxSeconds;
      if (phraseEnded || reachedMaximum) this.flush();
    };
    this.sources.forEach((source) => source.connect(this.processor!));
    this.processor.connect(this.silentGain);
    this.silentGain.connect(this.context.destination);
  }

  async pause(): Promise<void> {
    if (!this.context || this.paused) return;
    this.flush();
    this.paused = true;
    this.onLevel(0);
    if (this.context.state === "running") await this.context.suspend();
  }

  async resume(): Promise<void> {
    if (!this.context || !this.paused) return;
    if (this.context.state === "suspended") await this.context.resume();
    this.paused = false;
  }

  async stop(flush = true): Promise<void> {
    if (flush) this.flush();
    else { this.chunks = []; this.sampleCount = 0; this.silenceSamples = 0; this.heardSpeech = false; }
    if (this.processor) this.processor.onaudioprocess = null;
    this.sources.forEach((source) => source.disconnect());
    this.processor?.disconnect();
    this.silentGain?.disconnect();
    this.streams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.context = null;
    this.streams = [];
    this.sources = [];
    this.processor = null;
    this.silentGain = null;
    this.paused = false;
    this.onLevel(0);
  }

  private flush(): void {
    if (!this.sampleCount) return;
    const joined = new Int16Array(this.sampleCount);
    let offset = 0;
    for (const chunk of this.chunks) {
      joined.set(chunk, offset);
      offset += chunk.length;
    }
    this.chunks = [];
    this.sampleCount = 0;
    this.silenceSamples = 0;
    this.heardSpeech = false;
    this.onChunk(int16ToBase64(joined));
  }
}

function downsample(input: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (sourceRate === targetRate) return new Float32Array(input);
  const ratio = sourceRate / targetRate;
  const length = Math.max(1, Math.floor(input.length / ratio));
  const output = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(input.length - 1, left + 1);
    const fraction = position - left;
    output[index] = input[left] * (1 - fraction) + input[right] * fraction;
  }
  return output;
}

function floatToInt16(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]));
    output[index] = Math.round(sample < 0 ? sample * 32768 : sample * 32767);
  }
  return output;
}

function int16ToBase64(input: Int16Array): string {
  const bytes = new Uint8Array(input.buffer, input.byteOffset, input.byteLength);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 32_768) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
  }
  return btoa(binary);
}
