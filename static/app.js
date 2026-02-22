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
        midiLog: [],                // scrolling text MIDI output
        midiLogMax: 200,
        _pendingMidiNotes: [],      // accumulator for current step

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
                if (this.showMidi) this.rebuildPianoRollNotes();
            } else if (msg.type === 'playhead') {
                this.currentStep = msg.step;
                this.scrollPlayheadIntoView();
                if (this.showMidi && this._pendingMidiNotes.length > 0) {
                    this.flushMidiLog();
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
                    this._pendingMidiNotes.push({
                        pattern: msg.pattern,
                        step: msg.step,
                        notes: msg.notes,
                        cc: msg.cc || [],
                    });
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
            'euclid', 'arp', 'auto', 'swing', 'cc', 'pc', 'panic', 'ports',
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
                this.midiLog = [];
                this._pendingMidiNotes = [];
            }
        },

        flushMidiLog() {
            // Group accumulated midi_out events by pattern, format as one log line per step
            const groups = this._pendingMidiNotes;
            this._pendingMidiNotes = [];
            if (groups.length === 0) return;

            // All groups share the same step (they fired on the same sequencer tick)
            const step = groups[0].step;
            const parts = [];
            for (const g of groups) {
                const strs = [];
                // Note info
                for (const n of g.notes) {
                    const name = n.ch === 9 ? this.drumName(n.note) : n.name;
                    let s = name + ' v' + n.vel;
                    if (n.gate !== 1) s += ' g' + n.gate;
                    if (n.swing > 0) s += ' sw' + n.swing;
                    strs.push(s);
                }
                // CC info
                for (const c of (g.cc || [])) {
                    strs.push('CC' + c.cc + '=' + c.value);
                }
                if (strs.length > 0) {
                    parts.push(g.pattern + ': ' + strs.join(', '));
                }
            }
            const line = String(step).padStart(3) + ' │ ' + parts.join('  ·  ');
            this.midiLog.push(line);
            if (this.midiLog.length > this.midiLogMax) {
                this.midiLog = this.midiLog.slice(-this.midiLogMax);
            }
            this.scrollMidiLog();
        },

        scrollMidiLog() {
            this.$nextTick(() => {
                const el = this.$refs.midiLogContainer;
                if (el) el.scrollTop = el.scrollHeight;
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
                auto:    ['auto', '<pattern>', 'cc<N>', '<step:val ...>'],
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