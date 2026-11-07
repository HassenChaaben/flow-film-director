# Programmatic Video Editing with Remotion & React

A comprehensive developer guide for AI agents and video creators to build, edit, preview, and render timeline-based videos programmatically using **Remotion** and the official **`remotion-dev/skills`** pack.

---

## Why Remotion?

- **Zero Desktop Software**: No Adobe Premiere, DaVinci Resolve, or Final Cut Pro required. Everything runs in Node.js, React, and TypeScript.
- **Code-Driven Timelines**: Video edits, transitions, motion graphics, and audio ducking are pure React components controlled by code and parameters.
- **Deterministic & Scalable**: Automate personalized video generation for thousands of users from a single template with dynamic props.
- **Interactive Studio**: Real-time browser preview player with scrubbing, frame-stepping, and visual debugging (`npx remotion studio`).

---

## 1. Environment Verification & Skill Installation

### Step 1: Verify Node.js (v16+)
```bash
node --version  # Must be v16+, recommended v20+
npm --version
```

### Step 2: Install Remotion Agent Skills
Install the official skill suite non-interactively across your agent environments:
```bash
npx -y skills@latest add remotion-dev/skills -g -y
```

Installed skills include:
- `remotion-best-practices`: Core guidelines, FPS, spring physics, and project architecture.
- `remotion-create`: Scaffolding new compositions and templates.
- `remotion-markup`: Writing clean Remotion JSX (`<Sequence>`, `<Video>`, `<Audio>`, `<AbsoluteFill>`).
- `remotion-studio`: Starting and interacting with the local Studio preview server.
- `remotion-render`: Headless rendering to MP4, WebM, ProRes, or GIF via Chromium.
- `remotion-captions`: Animated word-by-word captions and kinetic typography.
- `remotion-multimedia`: Video trimming, cropping, and audio metadata extraction.

---

## 2. Scaffolding a Remotion Workspace

To create a clean, blank Remotion video project:
```bash
npx create-video@latest --yes --blank my-video-project
cd my-video-project
```

### Project Structure
```text
my-video-project/
├── package.json
├── remotion.config.ts        # Configuration (Chromium flags, codecs, resolution)
├── src/
│   ├── Root.tsx              # Registers all video compositions
│   ├── Composition.tsx       # Your main video timeline component
│   └── index.ts              # Entry point for Studio and renderer
└── public/                   # Media assets (videos, images, audio, fonts)
```

---

## 3. Real-World Production Composition Example

Below is a complete, production-tested Remotion composition that stitches together 3 scene clips, animates a cinematic lower-third title with spring physics, and ducks background music during speech:

```tsx
// src/CinematicFilm.tsx
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Video,
} from 'remotion';

interface SceneProps {
  title: string;
  creatorName: string;
}

export const CinematicFilm: React.FC<SceneProps> = ({
  title = "Hassen's Journey",
  creatorName = "Hassen Ben Chaaben",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Smooth entrance spring for lower-third banner
  const titleEntrance = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  // Calculate audio ducking volume: dip music by 12dB during dialogue
  const musicVolume = interpolate(
    frame,
    [0, 15, 180, 210, 360, 390],
    [0.4, 0.15, 0.15, 0.4, 0.4, 0.15],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  return (
    <AbsoluteFill style={{ backgroundColor: '#000' }}>
      {/* Background Music Track with Dynamic Ducking */}
      <Audio src={staticFile('audio/soundtrack.mp3')} volume={musicVolume} />

      {/* Scene 1: Tunisia Origin (Frames 0 to 180 = 6 seconds at 30 fps) */}
      <Sequence from={0} durationInFrames={180}>
        <Video src={staticFile('clips/scene-01.mp4')} />
      </Sequence>

      {/* Scene 2: Arrival in Italy (Frames 180 to 360 = 6 seconds) */}
      <Sequence from={180} durationInFrames={180}>
        <Video src={staticFile('clips/scene-02.mp4')} />
      </Sequence>

      {/* Scene 3: AI Laboratory (Frames 360 to 540 = 6 seconds) */}
      <Sequence from={360} durationInFrames={180}>
        <Video src={staticFile('clips/scene-03.mp4')} />
      </Sequence>

      {/* Animated Cinematic Lower-Third Overlay */}
      <Sequence from={30} durationInFrames={150}>
        <AbsoluteFill
          style={{
            justifyContent: 'flex-end',
            padding: 80,
            opacity: titleEntrance,
            transform: `translateY(${(1 - titleEntrance) * 40}px)`,
          }}
        >
          <div
            style={{
              background: 'rgba(15, 23, 42, 0.85)',
              padding: '16px 28px',
              borderRadius: 12,
              borderLeft: '4px solid #38bdf8',
              maxWidth: 600,
              backdropFilter: 'blur(8px)',
            }}
          >
            <h1
              style={{
                color: '#fff',
                fontSize: 32,
                fontFamily: 'system-ui, sans-serif',
                margin: 0,
              }}
            >
              {title}
            </h1>
            <p
              style={{
                color: '#94a3b8',
                fontSize: 18,
                fontFamily: 'system-ui, sans-serif',
                margin: '4px 0 0 0',
              }}
            >
              Featuring {creatorName}
            </p>
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
```

### Registering in `src/Root.tsx`:
```tsx
import { Composition } from 'remotion';
import { CinematicFilm } from './CinematicFilm';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="CinematicFilm"
      component={CinematicFilm}
      durationInFrames={540} // 18 seconds total
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{
        title: "Hassen's Journey to AI Success",
        creatorName: "Hassen Ben Chaaben",
      }}
    />
  );
};
```

---

## 4. Previewing & Headless Rendering

### Non-Blocking Studio Preview Server
Start Remotion Studio without popping up browser windows:
```bash
npx remotion studio --no-open
```
Opens interactive studio player at `http://localhost:3000`.

### Headless Production Render
Render to 1080p H.264 MP4:
```bash
npx remotion render CinematicFilm out/film-master.mp4 --concurrency=4
```
Render with dynamic JSON props:
```bash
npx remotion render CinematicFilm out/personalized-marwen.mp4 --props='{"creatorName": "Marwen", "title": "Marwen Story"}'
```

---

## 5. Remotion Best Practices for AI Video Pipelines

1. **Avoid Hardcoded Frame Numbers**: Use `durationInFrames` and math relative to `fps` so changing from 30 fps to 60 fps doesn't break animation timings.
2. **Always Use `<Sequence>` for Cuts**: Splicing clips sequentially with `<Sequence from={...} durationInFrames={...}>` ensures accurate audio/video sync and prevents memory leaks from unmounted video tags.
3. **Use `staticFile()` for Local Assets**: Place all videos, images, and audio into `public/` and reference them via `staticFile('clips/scene-01.mp4')`.
4. **Spring Over Easing**: Always prefer `spring()` over manual CSS transitions for natural, physically realistic title animations.
