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
        activeTab: 'command',
        aiLog: [],
        selectedPattern: null,
        collapsedPatterns: {},
        scrollIndex: 0,
        showHelp: false,
        showMidi: false,
        macroEditor: { open: false, name: '', commands: '', params: [] },
        midiLog: [],                // scrolling text MIDI output
        midiLogMax: 200,
        _pendingMidiNotes: [],      // accumulator for current step
        layoutWidth: localStorage.getItem('layoutWidth') || 'none',
        layoutPresets: [
            { label: 'Compact', value: '960px' },
            { label: 'Normal', value: '1200px' },
            { label: 'Wide', value: '1600px' },
            { label: 'Full', value: 'none' },
        ],

        // Command history
        commandHistory: JSON.parse(localStorage.getItem('commandHistory') || '[]'),
        historyIndex: -1,

        // Lifecycle
        init() {
            this.log = JSON.parse(localStorage.getItem('log') || '[]');
            this.aiLog = JSON.parse(localStorage.getItem('aiLog') || '[]');
            // Migrate old layoutWidth values
            if (this.layoutWidth === '100%') {
                this.layoutWidth = 'none';
                localStorage.setItem('layoutWidth', 'none');
            }
            this.applyLayoutWidth();
            this.connect();
            this.loadCommandMeta();
            window.addEventListener('keydown', (e) => this.handleGlobalKeydown(e));
            this.$nextTick(() => this.scrollLog());
        },

        connect() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${proto}//${window.location.host}/ws`);
            this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
            this.ws.onclose = () => setTimeout(() => this.connect(), 1000);
            this.ws.onerror = () => {};
        },

        async loadCommandMeta() {
            try {
                const res = await fetch('/api/commands');
                const data = await res.json();
                this.commands = [];
                this.hints = {};
                for (const cmd of data) {
                    this.commands.push(cmd.name);
                    for (const alias of (cmd.aliases || [])) {
                        this.commands.push(alias);
                    }
                    if (cmd.hint_args && cmd.hint_args.length > 0) {
                        this.hints[cmd.name] = [cmd.name, ...cmd.hint_args];
                    }
                }
            } catch (err) {
                // Fallback: commands will be empty until server responds
            }
        },

        onMessage(msg) {
            if (msg.type === 'state') {
                this.patterns = msg.patterns;
                this.bpm = msg.bpm;
                this.playing = msg.playing;
                // Clear stale selection if pattern was deleted
                if (this.selectedPattern && !this.patterns[this.selectedPattern]) {
                    this.selectedPattern = null;
                }
                // Auto-select first pattern if nothing selected
                if (!this.selectedPattern) {
                    const names = Object.keys(this.patterns);
                    if (names.length > 0) this.selectedPattern = names[0];
                }
                // Clamp scrollIndex when patterns are deleted
                const maxScroll = Math.max(0, Object.keys(this.patterns).length - 1);
                if (this.scrollIndex > maxScroll) this.scrollIndex = maxScroll;
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
            } else if (msg.type === 'ui') {
                if (msg.select) {
                    this.selectedPattern = msg.select;
                    this.scrollToPattern(msg.select);
                }
                if (msg.scroll === 'up') this.scrollUp();
                if (msg.scroll === 'down') this.scrollDown();
                if (msg.toggle === 'midi') this.toggleMidiMonitor();
                if (msg.toggle === 'help') this.showHelp = !this.showHelp;
                if (msg.fold) this.collapsedPatterns[msg.fold] = true;
                if (msg.unfold) this.collapsedPatterns[msg.unfold] = false;
                if (msg.macro_edit) {
                    this.macroEditor = {
                        open: true,
                        name: msg.macro_edit,
                        commands: (msg.commands || []).join('\n'),
                        params: msg.params || [],
                    };
                }
                if (msg.tab) this.switchTab(msg.tab);
                if (msg.width) this.setLayoutWidth(msg.width);
                if (msg.macro_saved) {
                    this.macroEditor.open = false;
                }
            } else if (msg.type === 'midi_out') {
                if (this.showMidi) {
                    this._pendingMidiNotes.push({
                        pattern: msg.pattern,
                        step: msg.step,
                        notes: msg.notes,
                        cc: msg.cc || [],
                    });
                    // Flush immediately when not playing (e.g. tap command)
                    if (!this.playing) {
                        this.flushMidiLog();
                    }
                }
            }
        },

        sendCommand(line) {
            if (!line.trim()) return;
            this.activeTab = 'command';
            this.log.push(`> ${line}`);
            this.scrollLog();
            this.ws.send(JSON.stringify({ type: 'command', line }));
            // Add to history (avoid duplicates at end)
            if (this.commandHistory[this.commandHistory.length - 1] !== line) {
                this.commandHistory.push(line);
                localStorage.setItem('commandHistory', JSON.stringify(this.commandHistory));
            }
            this.historyIndex = -1;
            this.commandInput = '';
        },

        commands: [],
        drumNames: [
            'kick', 'snare', 'clap', 'hihat', 'ohh', 'tom1', 'tom2', 'tom3',
            'crash', 'ride', 'cowbell', 'rimshot',
        ],
        hints: {},

        handleCommandKeydown(event) {
            if (event.key === ' ' && this.commandInput === '') {
                event.preventDefault();
                this.sendCommand(this.playing ? 'stop' : 'play');
                return;
            }
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

        handleGlobalKeydown(event) {
            if (event.ctrlKey && event.key === ' ') {
                event.preventDefault();
                this.sendCommand(this.playing ? 'stop' : 'play');
            }
            if (event.ctrlKey && event.key === 'Tab') {
                event.preventDefault();
                this.switchTab('toggle');
            }
            if (event.ctrlKey && ['Digit1','Digit2','Digit3','Digit4'].includes(event.code)) {
                event.preventDefault();
                const idx = parseInt(event.code.slice(-1)) - 1;
                this.setLayoutWidth(this.layoutPresets[idx].value);
            }
        },

        switchTab(target) {
            if (target === 'toggle' || !target) {
                this.activeTab = this.activeTab === 'command' ? 'ai' : 'command';
            } else if (target === 'command' || target === 'ai') {
                this.activeTab = target;
            }
        },

        setLayoutWidth(value) {
            this.layoutWidth = value;
            localStorage.setItem('layoutWidth', value);
            this.applyLayoutWidth();
        },

        applyLayoutWidth() {
            const el = document.querySelector('main');
            if (!el) return;
            if (this.layoutWidth === 'none') {
                el.style.removeProperty('max-width');
            } else {
                el.style.setProperty('max-width', this.layoutWidth, 'important');
            }
        },

        get shortcuts() {
            return [
                { keys: 'Ctrl+Space', label: 'Play/Stop' },
                { keys: 'Ctrl+Tab', label: 'Switch Tab' },
                { keys: 'Ctrl+1-4', label: 'Width' },
            ];
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
            this.activeTab = 'ai';
            this.aiLoading = true;
            this.aiLog.push(`\uD83E\uDD16 ${message}`);
            this.scrollAiLog();
            try {
                const res = await fetch('/api/ai', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message,
                        context: {
                            selectedPattern: this.selectedPattern,
                            playing: this.playing,
                            bpm: this.bpm,
                            patternNames: this.patternNames,
                            recentCommands: this.commandHistory.slice(-20),
                        },
                    }),
                });
                const data = await res.json();
                if (data.comments) {
                    data.comments.forEach(c => this.aiLog.push(`  💬 ${c}`));
                }
                if (data.commands) {
                    data.commands.forEach(cmd => this.aiLog.push(`  > ${cmd}`));
                }
                if (data.output) {
                    data.output.forEach(line => this.aiLog.push(line));
                }
                if (data.detail) {
                    this.aiLog.push(`Error: ${data.detail}`);
                }
            } catch (err) {
                this.aiLog.push(`Error: ${err.message}`);
            }
            this.aiLoading = false;
            this.aiInput = '';
            this.scrollAiLog();
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
            // Cap log size and persist
            if (this.log.length > 500) {
                this.log = this.log.slice(-500);
            }
            localStorage.setItem('log', JSON.stringify(this.log));
            this.$nextTick(() => {
                const container = this.$refs.logContainer;
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        },

        scrollAiLog() {
            if (this.aiLog.length > 500) {
                this.aiLog = this.aiLog.slice(-500);
            }
            localStorage.setItem('aiLog', JSON.stringify(this.aiLog));
            this.$nextTick(() => {
                const container = this.$refs.aiLogContainer;
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
            const stepLabel = step < 0 ? '  ·' : String(step).padStart(3);
            const line = stepLabel + ' │ ' + parts.join('  ·  ');
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

        selectPattern(name) {
            this.selectedPattern = name;
            this.scrollToPattern(name);
        },

        scrollUp() {
            if (this.scrollIndex > 0) this.scrollIndex--;
        },

        scrollDown() {
            if (this.scrollIndex < this.patternNames.length - 1) this.scrollIndex++;
        },

        scrollToPattern(name) {
            const idx = this.patternNames.indexOf(name);
            if (idx >= 0) this.scrollIndex = idx;
        },

        get visiblePatterns() {
            return this.patternNames.slice(this.scrollIndex);
        },

        get selectedPatternData() {
            if (!this.selectedPattern || !this.patterns[this.selectedPattern]) return null;
            return this.patterns[this.selectedPattern];
        },

        getStepDensity(pat) {
            if (!pat) return [];
            const result = [];
            for (let s = 0; s < pat.steps; s++) {
                const stepData = pat.data[String(s)];
                result.push(stepData && stepData.length > 0);
            }
            return result;
        },

        togglePattern(name) {
            this.collapsedPatterns[name] = !this.collapsedPatterns[name];
        },

        saveMacro() {
            const commands = this.macroEditor.commands.split('\n').filter(l => l.trim());
            this.ws.send(JSON.stringify({
                type: 'macro_save',
                name: this.macroEditor.name,
                commands,
            }));
        },

        cancelMacroEdit() {
            this.macroEditor.open = false;
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
            if (channel === 9) return this.drumName(midi) + ' ' + this.noteName(midi);
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

            const schema = this.hints[cmd];
            if (!schema) {
                if (argc === 0) {
                    const matches = Object.keys(this.hints).filter(c => c.startsWith(cmd));
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