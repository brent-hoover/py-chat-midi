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
        showMidi: false,
        pianoRollColumns: [],   // array of { notes: [{note, vel, ch}] } per step
        pianoRollMaxCols: 128,
        pianoRollNotes: [],     // sorted unique MIDI note numbers (high to low)

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
                if (this.showMidi) {
                    // Push empty column to keep roll scrolling on silent steps
                    if (!this._pendingMidiCol) {
                        this.pushPianoRollColumn([]);
                        this.drawPianoRoll();
                    }
                    this._pendingMidiCol = false;
                }
            } else if (msg.type === 'output') {
                this.log.push(msg.text);
                this.scrollLog();
            } else if (msg.type === 'transport') {
                this.playing = msg.playing;
                this.bpm = msg.bpm;
                if (!msg.playing) {
                    this.currentStep = -1;
                }
            } else if (msg.type === 'midi_out') {
                if (this.showMidi) {
                    this.pushPianoRollColumn(msg.notes);
                    this.drawPianoRoll();
                    this._pendingMidiCol = true;
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

        commands: [
            'play', 'stop', 'bpm', 'new', 'list', 'delete', 'mute', 'unmute',
            'solo', 'put', 'vel', 'remove', 'clear', 'replace', 'show',
            'euclid', 'arp', 'swing', 'cc', 'pc', 'panic', 'ports',
            'drums', 'drummap', 'save', 'load', 'run', 'help', 'quit',
        ],
        drumNames: [
            'kick', 'snare', 'clap', 'hihat', 'ohh', 'tom1', 'tom2', 'tom3',
            'crash', 'ride', 'cowbell', 'rimshot',
        ],

        handleCommandKeydown(event) {
            if (event.key === 'Tab') {
                event.preventDefault();
                this.tabComplete();
                return;
            }
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

        tabComplete() {
            const input = this.commandInput;
            const parts = input.split(/\s+/);
            const isFirstWord = parts.length <= 1;
            const partial = parts[parts.length - 1].toLowerCase();

            let candidates = [];
            if (isFirstWord) {
                candidates = this.commands.filter(c => c.startsWith(partial));
            } else {
                // Complete pattern names, then drum names
                const patNames = Object.keys(this.patterns);
                candidates = patNames.filter(n => n.toLowerCase().startsWith(partial));
                if (candidates.length === 0) {
                    candidates = this.drumNames.filter(n => n.startsWith(partial));
                }
            }

            if (candidates.length === 1) {
                parts[parts.length - 1] = candidates[0];
                this.commandInput = parts.join(' ') + ' ';
            } else if (candidates.length > 1) {
                // Find common prefix
                let prefix = candidates[0];
                for (const c of candidates) {
                    while (!c.startsWith(prefix)) {
                        prefix = prefix.slice(0, -1);
                    }
                }
                if (prefix.length > partial.length) {
                    parts[parts.length - 1] = prefix;
                    this.commandInput = parts.join(' ');
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

        toggleMidiMonitor() {
            this.showMidi = !this.showMidi;
            if (!this.showMidi) {
                this.pianoRollColumns = [];
                this.pianoRollNotes = [];
            } else {
                this.rebuildPianoRollNotes();
                this.$nextTick(() => this.drawPianoRoll());
            }
        },

        rebuildPianoRollNotes() {
            const notes = new Set();
            this._noteChannels = {};
            for (const pat of Object.values(this.patterns)) {
                for (const stepNotes of Object.values(pat.data)) {
                    for (const [note] of stepNotes) {
                        notes.add(note);
                        this._noteChannels[note] = pat.channel;
                    }
                }
            }
            // Sort low to high for left-to-right
            this.pianoRollNotes = [...notes].sort((a, b) => a - b);
            this.updatePianoLabels();
        },

        updatePianoLabels() {
            const container = this.$refs.pianoLabels;
            if (!container) return;
            container.innerHTML = '';
            const notes = this.pianoRollNotes;
            // Sort low to high for left-to-right display
            const sorted = [...notes].sort((a, b) => a - b);
            const hasDrums = Object.values(this.patterns).some(p => p.channel === 9);
            const colWidth = this._pianoColWidth || 30;
            for (const note of sorted) {
                const div = document.createElement('div');
                div.className = 'piano-roll-label';
                div.style.width = colWidth + 'px';
                div.style.minWidth = colWidth + 'px';
                const ch = this._noteChannels ? this._noteChannels[note] : undefined;
                div.textContent = ch === 9 ? this.drumName(note) : this.noteName(note);
                container.appendChild(div);
            }
        },

        pushPianoRollColumn(notes) {
            // Add any new notes to the pitch list
            let changed = false;
            for (const n of notes) {
                if (!this.pianoRollNotes.includes(n.note)) {
                    changed = true;
                }
            }
            if (changed) this.rebuildPianoRollNotes();

            this.pianoRollColumns.push(notes);
            if (this.pianoRollColumns.length > this.pianoRollMaxCols) {
                this.pianoRollColumns = this.pianoRollColumns.slice(-this.pianoRollMaxCols);
            }
        },

        drawPianoRoll() {
            const canvas = this.$refs.pianoRoll;
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;

            const numNotes = this.pianoRollNotes.length;
            if (numNotes === 0) return;

            // X = notes (low to high, left to right), Y = time (top = newest)
            const rect = canvas.parentElement.getBoundingClientRect();
            const labelBarHeight = 20;
            const w = rect.width - 6;
            const colWidth = Math.max(20, Math.min(50, (w - 28) / numNotes));
            const rowHeight = 6;
            const maxRows = 64;
            const h = 180;
            const visibleRows = Math.floor(h / rowHeight);
            const rows = this.pianoRollColumns.slice(-visibleRows);

            // Store for label sizing
            this._pianoColWidth = colWidth;

            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            // Clear
            ctx.fillStyle = '#0d0d14';
            ctx.fillRect(0, 0, w, h);

            // Note index map (sorted low to high)
            const noteToCol = {};
            this.pianoRollNotes.forEach((n, i) => noteToCol[n] = i);

            const xOffset = 28; // space for row numbers

            // Draw column grid lines
            ctx.strokeStyle = '#1a1a2e';
            ctx.lineWidth = 0.5;
            for (let c = 0; c <= numNotes; c++) {
                const x = xOffset + c * colWidth;
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, h);
                ctx.stroke();
            }

            // Draw row grid lines
            for (let r = 0; r <= visibleRows; r++) {
                const y = r * rowHeight;
                ctx.beginPath();
                ctx.moveTo(xOffset, y);
                ctx.lineTo(xOffset + numNotes * colWidth, y);
                ctx.stroke();
            }

            // Draw notes — newest at bottom, oldest at top
            for (let r = 0; r < rows.length; r++) {
                const y = h - (rows.length - r) * rowHeight;
                if (y < 0) continue;
                for (const n of rows[r]) {
                    const col = noteToCol[n.note];
                    if (col === undefined) continue;
                    const x = xOffset + col * colWidth;
                    const brightness = 0.4 + (n.vel / 127) * 0.6;
                    const hue = n.ch === 9 ? 140 : 270;
                    ctx.fillStyle = `hsla(${hue}, 70%, ${brightness * 60}%, ${brightness})`;
                    ctx.fillRect(x + 1, y, colWidth - 2, rowHeight - 1);
                }
            }

            // Draw current row indicator (bottom row)
            if (rows.length > 0) {
                const y = h - rowHeight;
                ctx.fillStyle = 'rgba(250, 204, 21, 0.15)';
                ctx.fillRect(xOffset, y, numNotes * colWidth, rowHeight);
            }

            // Draw step numbers on left
            ctx.fillStyle = '#444';
            ctx.font = '9px monospace';
            ctx.textAlign = 'right';
            for (let r = 0; r < rows.length; r++) {
                const y = h - (rows.length - r) * rowHeight;
                if (y < 5) continue;
                if (r % 4 === 0) {
                    ctx.fillText(String(r), xOffset - 4, y + rowHeight - 1);
                }
            }

            // Update labels
            this.updatePianoLabels();
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

        get commandHint() {
            const input = this.commandInput.trim();
            if (!input) return 'Type a command or press Tab to complete';

            const parts = input.split(/\s+/);
            const cmd = parts[0].toLowerCase();
            const argc = parts.length - 1;
            const patNames = Object.keys(this.patterns);

            const hints = {
                bpm:     ['bpm', '<tempo>'],
                new:     ['new', '<name>', '[steps=16]', '[channel=0]'],
                delete:  ['delete', '<pattern>'],
                put:     ['put', '<pattern>', '<steps>', '<notes>', '[vel=100]', '[gate=1]'],
                vel:     ['vel', '<pattern>', '<steps>', '<note>', '<velocity>'],
                remove:  ['remove', '<pattern>', '<steps>', '<note>'],
                clear:   ['clear', '<pattern>', '[steps]'],
                replace: ['replace', '<pattern>', '<old_note>', '<new_note>'],
                show:    ['show', '<pattern>'],
                mute:    ['mute', '<pattern>', '[note]'],
                unmute:  ['unmute', '[pattern]'],
                solo:    ['solo', '<pattern>', '[note]'],
                swing:   ['swing', '<pattern>', '<0-100>', '[note]'],
                euclid:  ['euclid', '<pattern>', '<hits>', '[notes]', '[vel]'],
                arp:     ['arp', '<pattern>', '<notes>', '<up|down|updown|random>'],
                cc:      ['cc', '<channel>', '<cc#>', '<value>'],
                pc:      ['pc', '<channel>', '<program>'],
                drummap: ['drummap', '<name>', '<note>', '| reset'],
                save:    ['save', '[file.json]'],
                load:    ['load', '<file.json>'],
                run:     ['run', '<file.txt>'],
            };

            const schema = hints[cmd];
            if (!schema) {
                if (argc === 0) {
                    const matches = Object.keys(hints).filter(c => c.startsWith(cmd));
                    if (matches.length > 0 && matches.length <= 5) {
                        return matches.join('  ');
                    }
                }
                return '';
            }

            // Build hint with completed args dimmed, next arg highlighted
            let hint = '';
            const needsPattern = schema.length > 1 && schema[1].includes('pattern');
            for (let i = 0; i < schema.length; i++) {
                if (i > 0) hint += ' ';
                if (i <= argc) {
                    // Already typed — show what they typed
                    hint += parts[i] || '';
                } else if (i === argc + 1) {
                    // Next expected arg — show options if applicable
                    if (needsPattern && i === 1 && patNames.length > 0) {
                        hint += '[' + patNames.join('|') + ']';
                    } else {
                        hint += schema[i];
                    }
                } else {
                    hint += schema[i];
                }
            }
            return hint;
        },
    };
}