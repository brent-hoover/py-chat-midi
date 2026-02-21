function sequencer() {
    return {
        // State
        ws: null,
        patterns: {},
        bpm: 120,
        playing: false,
        currentStep: -1,
        log: [],
        commandInput: '',
        aiInput: '',
        aiLoading: false,
        collapsedPatterns: {},
        showHelp: false,

        // Command history
        commandHistory: [],
        historyIndex: -1,

        // Lifecycle
        init() {
            this.connect();
        },

        connect() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${proto}//${window.location.host}/ws`);
            this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
            this.ws.onclose = () => setTimeout(() => this.connect(), 1000);
            this.ws.onerror = () => {};
        },

        onMessage(msg) {
            if (msg.type === 'state') {
                this.patterns = msg.patterns;
                this.bpm = msg.bpm;
                this.playing = msg.playing;
            } else if (msg.type === 'playhead') {
                this.currentStep = msg.step;
                this.scrollPlayheadIntoView();
            } else if (msg.type === 'output') {
                this.log.push(msg.text);
                this.scrollLog();
            } else if (msg.type === 'transport') {
                this.playing = msg.playing;
                this.bpm = msg.bpm;
                if (!msg.playing) {
                    this.currentStep = -1;
                }
            }
        },

        sendCommand(line) {
            if (!line.trim()) return;
            this.log.push(`> ${line}`);
            this.scrollLog();
            this.ws.send(JSON.stringify({ type: 'command', line }));
            // Add to history (avoid duplicates at end)
            if (this.commandHistory[this.commandHistory.length - 1] !== line) {
                this.commandHistory.push(line);
            }
            this.historyIndex = -1;
            this.commandInput = '';
        },

        handleCommandKeydown(event) {
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                if (this.commandHistory.length === 0) return;
                if (this.historyIndex === -1) {
                    this.historyIndex = this.commandHistory.length - 1;
                } else if (this.historyIndex > 0) {
                    this.historyIndex--;
                }
                this.commandInput = this.commandHistory[this.historyIndex];
            } else if (event.key === 'ArrowDown') {
                event.preventDefault();
                if (this.historyIndex === -1) return;
                if (this.historyIndex < this.commandHistory.length - 1) {
                    this.historyIndex++;
                    this.commandInput = this.commandHistory[this.historyIndex];
                } else {
                    this.historyIndex = -1;
                    this.commandInput = '';
                }
            }
        },

        async sendAI(message) {
            if (!message.trim()) return;
            this.aiLoading = true;
            this.log.push(`\uD83E\uDD16 ${message}`);
            this.scrollLog();
            try {
                const res = await fetch('/api/ai', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message }),
                });
                const data = await res.json();
                if (data.commands) {
                    data.commands.forEach(cmd => this.log.push(`> ${cmd}`));
                }
                if (data.output) {
                    data.output.forEach(line => this.log.push(line));
                }
                if (data.detail) {
                    this.log.push(`Error: ${data.detail}`);
                }
            } catch (err) {
                this.log.push(`Error: ${err.message}`);
            }
            this.aiLoading = false;
            this.aiInput = '';
            this.scrollLog();
        },

        async saveSession() {
            try {
                const res = await fetch('/api/session');
                const data = await res.json();
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'session.json';
                a.click();
                URL.revokeObjectURL(url);
                this.log.push('  \u2713 Session saved');
                this.scrollLog();
            } catch (err) {
                this.log.push(`Error saving: ${err.message}`);
                this.scrollLog();
            }
        },

        async loadSession(event) {
            const file = event.target.files[0];
            if (!file) return;
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                const res = await fetch('/api/session', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: text,
                });
                const result = await res.json();
                this.log.push(`  \u2713 ${result.message}`);
                this.scrollLog();
            } catch (err) {
                this.log.push(`Error loading: ${err.message}`);
                this.scrollLog();
            }
            // Reset file input so same file can be loaded again
            event.target.value = '';
        },

        scrollLog() {
            this.$nextTick(() => {
                const container = this.$refs.logContainer;
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        },

        scrollPlayheadIntoView() {
            this.$nextTick(() => {
                const el = document.querySelector('.grid-cell.playhead');
                if (el) {
                    el.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' });
                }
            });
        },

        togglePattern(name) {
            this.collapsedPatterns[name] = !this.collapsedPatterns[name];
        },

        isCollapsed(name) {
            return !!this.collapsedPatterns[name];
        },

        // Grid helpers for a specific pattern
        getGridNotes(pat) {
            if (!pat) return [];
            const notes = new Set();
            for (const stepNotes of Object.values(pat.data)) {
                for (const [note] of stepNotes) {
                    notes.add(note);
                }
            }
            return [...notes].sort((a, b) => b - a);
        },

        noteName(midi) {
            const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
            const octave = Math.floor(midi / 12) - 1;
            return names[midi % 12] + octave;
        },

        drumName(midi) {
            const map = {
                36: 'kick', 37: 'rimshot', 38: 'snare', 39: 'clap',
                42: 'hihat', 43: 'tom3', 45: 'tom2', 46: 'ohh',
                48: 'tom1', 49: 'crash', 51: 'ride', 56: 'cowbell'
            };
            return map[midi] || this.noteName(midi);
        },

        noteLabelFor(midi, channel) {
            if (channel === 9) return this.drumName(midi);
            return this.noteName(midi);
        },

        hasNoteIn(pat, step, note) {
            if (!pat) return false;
            const stepData = pat.data[String(step)];
            if (!stepData) return false;
            return stepData.some(([n]) => n === note);
        },

        get patternNames() {
            return Object.keys(this.patterns);
        },
    };
}