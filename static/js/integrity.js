/**
 * Integrity card — GPS spoofing / anomaly detection UI.
 *
 * All rendering is defensive: if the /api/anomalies or /api/history endpoints
 * return { enabled: false } (or 404), the card hides itself entirely and the
 * rest of the dashboard keeps working.
 */

const Integrity = {
    cardEl: null,
    bodyEl: null,
    pillEl: null,
    summaryTextEl: null,
    toggleEl: null,
    toggleLabelEl: null,
    caretEl: null,
    timelineCanvas: null,
    driftCanvas: null,
    constellationsEl: null,
    logEl: null,
    timelineRangeEl: null,

    expanded: false,
    enabled: null,   // null = unknown yet, true/false once we've polled
    lastSummary: null,
    lastHistory: [],
    lastRecent: [],
    historyFetchPromise: null,

    CONSTELLATION_LABEL: {
        GP: 'GPS', SB: 'SBAS', QZ: 'QZSS',
        GL: 'GLONASS', GA: 'Galileo', GB: 'BeiDou',
        GI: 'NavIC',
    },
    CONSTELLATION_ORDER: ['GP', 'GA', 'GL', 'GB', 'QZ', 'GI', 'SB'],

    init() {
        this.cardEl = document.getElementById('integrity-card');
        if (!this.cardEl) return;
        this.bodyEl = document.getElementById('integrity-body');
        this.pillEl = document.getElementById('integrity-pill');
        this.summaryTextEl = document.getElementById('integrity-summary-text');
        this.toggleEl = document.getElementById('integrity-toggle');
        this.toggleLabelEl = this.toggleEl.querySelector('.toggle-label');
        this.caretEl = this.toggleEl.querySelector('.toggle-caret');
        this.timelineCanvas = document.getElementById('integrity-timeline');
        this.driftCanvas = document.getElementById('integrity-drift');
        this.constellationsEl = document.getElementById('integrity-constellations');
        this.logEl = document.getElementById('integrity-log');
        this.timelineRangeEl = document.getElementById('integrity-timeline-range');

        const header = document.getElementById('integrity-header');
        header.addEventListener('click', (e) => {
            // Ignore clicks on the button itself; handled below
            if (e.target.closest('#integrity-toggle')) return;
            this.toggle();
        });
        this.toggleEl.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });
    },

    toggle() {
        this.expanded = !this.expanded;
        this.cardEl.classList.toggle('collapsed', !this.expanded);
        this.toggleEl.setAttribute('aria-expanded', this.expanded ? 'true' : 'false');
        this.toggleLabelEl.textContent = this.expanded ? 'Hide' : 'Show';
        this.caretEl.textContent = this.expanded ? '▴' : '▾';
        if (this.expanded) {
            this.fetchHistory().then(() => this.render());
        }
    },

    /** Called by Dashboard.poll each tick with the /api/anomalies payload. */
    update(anomalyPayload) {
        if (!this.cardEl) return;

        if (!anomalyPayload || anomalyPayload.enabled === false) {
            if (this.enabled !== false) {
                this.enabled = false;
                this.cardEl.hidden = true;
            }
            return;
        }

        if (this.enabled !== true) {
            this.enabled = true;
            this.cardEl.hidden = false;
        }

        this.lastSummary = anomalyPayload.summary || {};
        this.lastActive = anomalyPayload.active || [];
        this.lastRecent = anomalyPayload.recent || [];
        this.renderHeader();

        // Only fetch history if expanded — save bandwidth when collapsed
        if (this.expanded) {
            this.fetchHistory().then(() => this.render());
        }
    },

    async fetchHistory() {
        if (this.historyFetchPromise) return this.historyFetchPromise;
        this.historyFetchPromise = fetch('/api/history?window=600')
            .then((r) => r.ok ? r.json() : { enabled: false, samples: [] })
            .then((data) => {
                this.lastHistory = data.samples || [];
            })
            .catch(() => { this.lastHistory = []; })
            .finally(() => { this.historyFetchPromise = null; });
        return this.historyFetchPromise;
    },

    renderHeader() {
        const summary = this.lastSummary || {};
        const worst = summary.worst_severity;
        let pillClass = 'integrity-pill pill-nominal';
        let pillText = 'Nominal';
        if (worst === 'critical') { pillClass = 'integrity-pill pill-critical'; pillText = 'Anomaly'; }
        else if (worst === 'warn') { pillClass = 'integrity-pill pill-warn'; pillText = 'Degraded'; }
        else if (worst === 'info')  { pillClass = 'integrity-pill pill-info'; pillText = 'Notice'; }
        this.pillEl.className = pillClass;
        this.pillEl.textContent = pillText;

        const count = summary.active_count || 0;
        const profile = summary.profile || 'stationary';
        if (count === 0) {
            this.summaryTextEl.textContent = `no active alerts · ${profile} profile`;
        } else {
            this.summaryTextEl.textContent =
                `${count} active alert${count > 1 ? 's' : ''} · ${profile} profile`;
        }
    },

    render() {
        if (!this.expanded) return;
        this.drawTimeline();
        this.drawDrift();
        this.renderConstellations();
        this.renderLog();
    },

    drawTimeline() {
        const canvas = this.timelineCanvas;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Background band
        ctx.fillStyle = 'rgba(42, 45, 58, 0.35)';
        ctx.fillRect(0, h / 2 - 4, w, 8);

        const samples = this.lastHistory || [];
        if (samples.length === 0) {
            ctx.fillStyle = '#5c6078';
            ctx.font = '12px sans-serif';
            ctx.fillText('Collecting samples…', 12, h / 2 + 4);
            return;
        }

        const t0 = samples[0].t;
        const t1 = samples[samples.length - 1].t;
        const span = Math.max(t1 - t0, 1);
        this.timelineRangeEl.textContent =
            `last ${Math.round(span / 60)} min (${samples.length} samples)`;

        // Draw fix-mode band: green where has_fix, red where not
        const barH = 8;
        const barY = h / 2 - barH / 2;
        for (let i = 0; i < samples.length; i++) {
            const s = samples[i];
            const x = ((s.t - t0) / span) * (w - 4) + 2;
            ctx.fillStyle = s.has_fix ? 'rgba(52, 211, 153, 0.55)' : 'rgba(248, 113, 113, 0.55)';
            ctx.fillRect(x, barY, 2, barH);
        }

        // Tick markers per recent anomaly
        const severityColor = {
            critical: '#f87171',
            warn: '#fbbf24',
            info: '#4a9eff',
        };
        const recent = this.lastRecent || [];
        for (const ev of recent) {
            if (ev.started_at < t0 || ev.started_at > t1) continue;
            const x = ((ev.started_at - t0) / span) * (w - 4) + 2;
            ctx.fillStyle = severityColor[ev.severity] || '#8b8fa3';
            ctx.beginPath();
            ctx.moveTo(x, 4);
            ctx.lineTo(x - 4, 14);
            ctx.lineTo(x + 4, 14);
            ctx.closePath();
            ctx.fill();
        }

        // Axis labels
        ctx.fillStyle = '#8b8fa3';
        ctx.font = '10px sans-serif';
        ctx.fillText(this._shortTime(t0), 4, h - 4);
        const rightLabel = 'now';
        const rightWidth = ctx.measureText(rightLabel).width;
        ctx.fillText(rightLabel, w - rightWidth - 4, h - 4);
    },

    drawDrift() {
        const canvas = this.driftCanvas;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const cx = w / 2, cy = h / 2;
        // Rings at 5m, 20m, 100m
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        ctx.lineWidth = 1;
        for (const r of [30, 60, 90]) {
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.stroke();
        }
        // Cross hairs
        ctx.beginPath();
        ctx.moveTo(cx - 100, cy); ctx.lineTo(cx + 100, cy);
        ctx.moveTo(cx, cy - 100); ctx.lineTo(cx, cy + 100);
        ctx.stroke();

        const samples = (this.lastHistory || []).filter(
            (s) => s.has_fix && s.lat != null && s.lon != null);
        if (samples.length < 2) {
            ctx.fillStyle = '#5c6078';
            ctx.font = '12px sans-serif';
            ctx.fillText('No fix history', cx - 35, cy + 4);
            return;
        }

        // Median reference (robust) over last N samples
        const lats = samples.map((s) => s.lat).sort((a, b) => a - b);
        const lons = samples.map((s) => s.lon).sort((a, b) => a - b);
        const midLat = lats[Math.floor(lats.length / 2)];
        const midLon = lons[Math.floor(lons.length / 2)];

        // Convert offsets to metres. 1 deg lat ≈ 111_320 m, lon scaled by cos(lat).
        const mPerDegLat = 111320;
        const mPerDegLon = 111320 * Math.cos(midLat * Math.PI / 180);

        let maxR = 10; // minimum scale so single-point clusters aren't a dot
        const points = samples.map((s) => {
            const dx = (s.lon - midLon) * mPerDegLon;
            const dy = (s.lat - midLat) * mPerDegLat;
            maxR = Math.max(maxR, Math.hypot(dx, dy));
            return { dx, dy, t: s.t };
        });

        // Scale ring labels to the data
        const scale = 90 / maxR;
        ctx.fillStyle = '#5c6078';
        ctx.font = '10px sans-serif';
        ctx.fillText(`±${maxR.toFixed(0)} m`, 6, 14);

        // Plot points; newer = brighter, current = ring
        const n = points.length;
        for (let i = 0; i < n; i++) {
            const p = points[i];
            const alpha = 0.2 + 0.6 * (i / Math.max(n - 1, 1));
            ctx.fillStyle = `rgba(74, 158, 255, ${alpha.toFixed(2)})`;
            ctx.beginPath();
            // Positive latitude offset = north = up (negative y in canvas)
            ctx.arc(cx + p.dx * scale, cy - p.dy * scale, 2, 0, Math.PI * 2);
            ctx.fill();
        }
        // Current
        const p = points[n - 1];
        ctx.strokeStyle = '#34d399';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx + p.dx * scale, cy - p.dy * scale, 5, 0, Math.PI * 2);
        ctx.stroke();
    },

    renderConstellations() {
        const samples = this.lastHistory || [];
        const latest = samples[samples.length - 1];
        const active = this.lastActive || [];
        const anomalousConsts = new Set(
            active.filter((a) => a.constellation).map((a) => a.constellation));

        const rows = [];
        if (latest && latest.constellations) {
            for (const cid of this.CONSTELLATION_ORDER) {
                const c = latest.constellations[cid];
                if (!c) continue;
                rows.push({ cid, ...c });
            }
            // Include any extras not in our ordered list
            for (const cid of Object.keys(latest.constellations)) {
                if (!this.CONSTELLATION_ORDER.includes(cid)) {
                    rows.push({ cid, ...latest.constellations[cid] });
                }
            }
        }

        if (rows.length === 0) {
            this.constellationsEl.innerHTML =
                '<div class="integrity-empty">No constellation data yet.</div>';
            return;
        }

        this.constellationsEl.innerHTML = rows.map((r) => {
            const cls = r.cid.toLowerCase();
            const label = this.CONSTELLATION_LABEL[r.cid] || r.cid;
            const usedCount = r.used || 0;
            const snr = (r.avg_snr || 0).toFixed(0);
            // Used bar maxes at 12 sats
            const usedPct = Math.min((usedCount / 12) * 100, 100);
            const flagged = anomalousConsts.has(r.cid);
            return `
                <div class="integrity-const-row ${flagged ? 'flagged' : ''}">
                    <span class="constellation-badge ${cls}">${label}</span>
                    <div class="integrity-const-bar">
                        <div class="integrity-const-bar-fill ${cls}" style="width:${usedPct}%"></div>
                    </div>
                    <span class="integrity-const-meta">${usedCount} used · ${snr} dB</span>
                </div>`;
        }).join('');
    },

    renderLog() {
        const events = (this.lastRecent || []).slice().reverse();
        if (events.length === 0) {
            this.logEl.innerHTML = '<li class="integrity-log-empty">No events recorded.</li>';
            return;
        }
        this.logEl.innerHTML = events.map((ev) => {
            const sev = ev.severity || 'info';
            const const_tag = ev.constellation
                ? `<span class="constellation-badge ${ev.constellation.toLowerCase()}">${this.CONSTELLATION_LABEL[ev.constellation] || ev.constellation}</span>`
                : '';
            return `
                <li class="integrity-log-item sev-${sev}">
                    <span class="log-time">${this._shortTime(ev.started_at)}</span>
                    <span class="log-sev sev-${sev}">${sev.toUpperCase()}</span>
                    <span class="log-kind">${ev.kind.replace(/_/g, ' ')}</span>
                    ${const_tag}
                    <span class="log-evidence">${ev.evidence || ''}</span>
                </li>`;
        }).join('');
    },

    _shortTime(t) {
        try {
            const d = new Date(t * 1000);
            if (isNaN(d.getTime())) return '--:--:--';
            return d.toISOString().substring(11, 19);
        } catch (e) {
            return '--:--:--';
        }
    },
};

document.addEventListener('DOMContentLoaded', () => Integrity.init());
