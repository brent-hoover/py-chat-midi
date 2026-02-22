# Music Theory & MIDI Concepts

## Music Theory Basics

### Notes and Pitch
Western music uses 12 notes per octave: C, C#, D, D#, E, F, F#, G, G#, A, A#, B — then the pattern repeats. The distance between any two adjacent notes is called a **semitone** (half step). Two semitones make a **whole tone** (whole step).

### Scales
A scale is a set of notes chosen from those 12, following a specific interval pattern. The most common:
- **Major scale** — whole, whole, half, whole, whole, whole, half (sounds "happy")
- **Minor scale (natural)** — whole, half, whole, whole, half, whole, whole (sounds "darker")
- **Pentatonic** — a 5-note subset of the major or minor scale, very commonly used in pop and electronic music

### Intervals
The distance between two notes. Key ones to know:
| Name | Semitones | Example (from C) |
|---|---|---|
| Unison | 0 | C → C |
| Minor 2nd | 1 | C → C# |
| Major 2nd | 2 | C → D |
| Minor 3rd | 3 | C → Eb |
| Major 3rd | 4 | C → E |
| Perfect 4th | 5 | C → F |
| Tritone | 6 | C → F# |
| Perfect 5th | 7 | C → G |
| Octave | 12 | C → C |

### Chords
A chord is three or more notes played together. The basics:
- **Major triad** — root + major 3rd + perfect 5th (bright)
- **Minor triad** — root + minor 3rd + perfect 5th (dark)
- **7th chords** — triads with an added 7th interval, common in jazz and funk

### Rhythm and Time
- **BPM (beats per minute)** — the tempo of the music
- **Time signature** — how beats are grouped. `4/4` means 4 beats per bar, each beat is a quarter note. `3/4` is waltz time.
- **Note lengths** — whole note (4 beats), half (2), quarter (1), eighth (0.5), sixteenth (0.25)
- **Bars/Measures** — a chunk of time defined by the time signature, e.g. 4 beats in 4/4

---

## MIDI

### What is MIDI?
MIDI (Musical Instrument Digital Interface) is a protocol for communicating musical instructions between devices and software. It carries **no audio** — just data describing what to play, how hard, and when.

### MIDI Notes
Each pitch is represented by a number from **0–127**:
- Middle C is **note 60** (also written as C4)
- Every semitone up is +1, every semitone down is -1
- C5 = 72, C3 = 48

A quick formula: `note number = (octave + 1) * 12 + semitone_offset`

### MIDI Messages
The core message types:

| Message | Data | Description |
|---|---|---|
| **Note On** | note, velocity | Start playing a note |
| **Note Off** | note, velocity | Stop playing a note |
| **Control Change (CC)** | controller number, value | Adjust a parameter (volume, pan, etc.) |
| **Program Change** | program number | Switch instrument/patch |
| **Pitch Bend** | 14-bit value | Smooth pitch shift up or down |
| **Aftertouch** | pressure value | Pressure applied after key press |

### Velocity
Velocity represents how hard a note is struck, ranging from **1–127** (0 is usually treated as Note Off). Higher velocity typically means louder and/or brighter, depending on the instrument.

### MIDI Channels
MIDI supports **16 channels** (1–16) on a single connection. Each channel can carry independent instrument data. Channel 10 is conventionally reserved for **drums/percussion**.

### Timing and Clocks
- **MIDI Clock** — a sync signal sent 24 times per quarter note (24 PPQN), used to keep devices in sync
- **MIDI Tick / Pulse** — the smallest unit of time in a MIDI sequence
- **PPQN (Pulses Per Quarter Note)** — resolution of a MIDI sequence. Common values: 24, 96, 480. Higher = more precise timing.

### Control Change (CC) Common Numbers
| CC # | Function |
|---|---|
| 1 | Modulation wheel |
| 7 | Channel volume |
| 10 | Pan |
| 11 | Expression |
| 64 | Sustain pedal |
| 74 | Brightness / filter cutoff |

### Step Sequencers and MIDI
A step sequencer divides time into discrete steps (e.g. 16 steps per bar in 4/4). Each step can trigger a Note On at a defined:
- **Pitch** (note number)
- **Velocity**
- **Duration** (gate length — how long the note stays on)

The sequencer advances steps based on a clock, either internal (driven by BPM) or external (MIDI Clock sync).

### MIDI in a DAW / Plugin Host
When a MIDI signal reaches an instrument plugin:
1. The host sends Note On → instrument starts rendering audio
2. The host sends Note Off → instrument releases the note
3. CC messages can automate parameters in real time

In a tool like **Element**, MIDI flows through the graph as a stream of these messages, 
routed from source (us) to destination (instrument plugin).