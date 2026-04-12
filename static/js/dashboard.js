/**
 * Dashboard controller - polls the API and updates all UI components.
 */

const Dashboard = {
    pollInterval: 2000,  // ms between API polls
    timer: null,
    errorCount: 0,

    init() {
        SkyView.init('skyview-canvas');
        SignalChart.init('signal-canvas');
        this.startClock();
        this.poll();
        this.timer = setInterval(() => this.poll(), this.pollInterval);
    },

    startClock() {
        const update = () => {
            const now = new Date();
            document.getElementById('clock').textContent =
                now.toISOString().substring(11, 19) + ' UTC';
        };
        update();
        setInterval(update, 1000);
    },

    async poll() {
        try {
            const resp = await fetch('/api/status');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this.errorCount = 0;
            this.updateConnectionStatus(true);
            this.updateGPS(data.gps);
            this.updateChrony(data.chrony);
            this.updatePrimarySourceBanner(data.chrony, data.gps);
            this.updateGPSD(data.gpsd, data.gps);
        } catch (err) {
            this.errorCount++;
            if (this.errorCount > 3) {
                this.updateConnectionStatus(false);
            }
        }
    },

    updateConnectionStatus(connected) {
        const el = document.getElementById('connection-status');
        if (connected) {
            el.textContent = 'Connected';
            el.className = 'status-badge connected';
        } else {
            el.textContent = 'Disconnected';
            el.className = 'status-badge disconnected';
        }
    },

    updateGPS(gps) {
        if (!gps) return;
        const fix = gps.fix;
        const summary = gps.summary;

        // Fix indicator
        const indicator = document.getElementById('fix-indicator');
        const fixText = document.getElementById('fix-text');
        fixText.textContent = fix.description;
        indicator.className = 'fix-indicator ' + (
            fix.has_fix ? (fix.mode === 3 ? 'fix-3d' : 'fix-2d') : 'no-fix'
        );

        // Fix details
        this.setText('gps-time', fix.utc_time || '--:--:--');
        this.setText('gps-date', fix.utc_date || '----/--/--');

        const timeValidEl = document.getElementById('time-valid');
        if (fix.time_available && !fix.valid) {
            timeValidEl.textContent = 'Time present but NOT validated (no fix)';
            timeValidEl.className = 'value warning';
        } else if (fix.time_available && fix.valid) {
            timeValidEl.textContent = 'Valid';
            timeValidEl.className = 'value good';
        } else {
            timeValidEl.textContent = 'No time data';
            timeValidEl.className = 'value error';
        }

        if (fix.has_fix && fix.latitude != null && fix.longitude != null) {
            this.setText('gps-position',
                fix.latitude.toFixed(6) + '°, ' + fix.longitude.toFixed(6) + '°');
        } else {
            this.setText('gps-position', 'n/a');
        }

        const pdop = fix.pdop != null ? fix.pdop.toFixed(1) : '--';
        const hdop = fix.hdop != null ? fix.hdop.toFixed(1) : '--';
        const vdop = fix.vdop != null ? fix.vdop.toFixed(1) : '--';
        this.setText('gps-dop', `${pdop} / ${hdop} / ${vdop}`);

        this.setText('sat-summary',
            `${summary.visible} seen / ${summary.tracked} tracked / ${summary.used} used`);

        // Satellite table
        this.updateSatelliteTable(gps.satellites);
        document.getElementById('sat-count-badge').textContent =
            `${summary.visible} visible, ${summary.tracked} tracked`;

        // Sky view and signal chart
        SkyView.update(gps.satellites);
        SignalChart.update(gps.satellites);
    },

    updateSatelliteTable(satellites) {
        const tbody = document.getElementById('satellite-tbody');
        if (!satellites || satellites.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#5c6078">No satellite data</td></tr>';
            return;
        }

        tbody.innerHTML = satellites.map(sat => {
            const constClass = sat.constellation.toLowerCase();
            const constName = {
                GP: 'GPS', SB: 'SBAS', QZ: 'QZSS',
                GL: 'GLONASS', GA: 'Galileo', GB: 'BeiDou',
            }[sat.constellation] || sat.constellation;

            const snrColor = this.snrColor(sat.snr);
            const snrWidth = Math.min(sat.snr / 50 * 100, 100);

            return `<tr>
                <td><span class="constellation-badge ${constClass}">${constName}</span></td>
                <td>${sat.prn}</td>
                <td>${sat.elevation.toFixed(1)}°</td>
                <td>${sat.azimuth.toFixed(1)}°</td>
                <td>
                    <div class="snr-bar-cell">
                        <span>${sat.snr > 0 ? sat.snr.toFixed(0) : '-'}</span>
                        <div class="snr-bar">
                            <div class="snr-bar-fill" style="width:${snrWidth}%;background:${snrColor}"></div>
                        </div>
                    </div>
                </td>
                <td style="color:${sat.tracked ? '#34d399' : '#5c6078'}">${sat.tracked ? 'Yes' : 'No'}</td>
                <td style="color:${sat.used ? '#34d399' : '#5c6078'}">${sat.used ? 'Yes' : 'No'}</td>
            </tr>`;
        }).join('');
    },

    snrColor(snr) {
        if (snr <= 0) return '#2a2d3a';
        if (snr < 15) return '#f87171';
        if (snr < 25) return '#fbbf24';
        if (snr < 35) return '#34d399';
        return '#4a9eff';
    },

    updateChrony(chrony) {
        if (!chrony) return;
        const t = chrony.tracking;

        const refDisplay = t.reference_name
            ? `${t.reference_name} (${t.reference_id.split(' ')[0] || ''})`
            : t.reference_id || '--';
        this.setText('chrony-ref', refDisplay);
        this.setText('chrony-stratum', t.stratum || '--');
        this.setText('chrony-systime', t.system_time_offset || '--');
        this.setText('chrony-offset', t.last_offset || '--');
        this.setText('chrony-rms', t.rms_offset || '--');
        this.setText('chrony-freq', t.frequency || '--');
        this.setText('chrony-skew', t.skew || '--');
        this.setText('chrony-rootdelay', t.root_delay || '--');
        this.setText('chrony-rootdisp', t.root_dispersion || '--');
        this.setText('chrony-interval', t.update_interval || '--');

        const leapEl = document.getElementById('chrony-leap');
        leapEl.textContent = t.leap_status || '--';
        leapEl.className = 'value' + (t.leap_status === 'Normal' ? ' good' : '');

        // Sources table
        this.updateSourcesTable(chrony.sources);
    },

    /**
     * Convert a chrony offset string (e.g. "+877us", "-141ms", "+0.000420814 seconds")
     * to seconds as a Number. Returns 0 for unparseable input so callers can
     * still display the reference system time.
     */
    parseOffsetSeconds(raw) {
        if (!raw || typeof raw !== 'string') return 0;
        const s = raw.trim();
        // Match: optional sign, digits/decimal, optional unit (ns|us|µs|ms|s|seconds)
        const m = s.match(/^([+-]?)(\d+(?:\.\d+)?)(?:\s*)(ns|us|µs|ms|s|seconds?)?/i);
        if (!m) return 0;
        const sign = m[1] === '-' ? -1 : 1;
        const magnitude = parseFloat(m[2]);
        if (!isFinite(magnitude)) return 0;
        const unit = (m[3] || 's').toLowerCase();
        const scale = {
            'ns': 1e-9,
            'us': 1e-6, 'µs': 1e-6,
            'ms': 1e-3,
            's': 1, 'second': 1, 'seconds': 1,
        }[unit] || 1;
        return sign * magnitude * scale;
    },

    /** Format a Date as HH:MM:SS UTC. */
    formatUtcTime(date) {
        if (!date || isNaN(date.getTime())) return '--:--:--';
        return date.toISOString().substring(11, 19);
    },

    /**
     * Build the primary-time-source banner from chrony tracking/sources plus
     * gpsd satellite info (for the constellation mix when GPS is primary).
     */
    updatePrimarySourceBanner(chrony, gps) {
        const card = document.getElementById('primary-source-card');
        const nameEl = document.getElementById('primary-source-name');
        const typeEl = document.getElementById('primary-source-type');
        const stratumEl = document.getElementById('primary-source-stratum');
        const timeEl = document.getElementById('primary-source-time');
        const constEl = document.getElementById('primary-source-constellations');

        // Default baseline class that gets replaced by source-{gps,pps,ntp,none}
        card.className = 'card primary-source-banner source-none';
        typeEl.className = 'banner-chip chip-type';

        const sources = (chrony && chrony.sources) || [];
        const tracking = (chrony && chrony.tracking) || {};
        const selected = sources.find(s => s.is_selected);

        if (!selected) {
            nameEl.textContent = 'No source selected';
            typeEl.textContent = '--';
            stratumEl.textContent = tracking.stratum
                ? `Stratum ${tracking.stratum}` : 'Stratum --';
            timeEl.textContent = '--:--:--';
            constEl.innerHTML = '';
            return;
        }

        // Classify the selected source for colour + label.
        // refid names "GPS"/"PPS" are our refclocks (mode '#').
        const refidUpper = (selected.name || '').toUpperCase();
        let kind = 'ntp';           // default: network NTP server
        let typeLabel = 'Network NTP';
        if (selected.mode === '#') {
            if (refidUpper === 'PPS') {
                kind = 'pps';
                typeLabel = 'PPS Refclock';
            } else {
                kind = 'gps';
                typeLabel = 'GPS Refclock';
            }
        }
        card.classList.add('source-' + kind);

        nameEl.textContent = selected.name;
        typeEl.textContent = typeLabel;
        stratumEl.textContent = `Stratum ${tracking.stratum || '--'}`;

        // UTC time reported by the selected source = now + its offset to system.
        // (For the selected source chrony *is* tracking it, so this is very close
        // to the system clock; the tiny offset mostly reflects residual error.)
        const offsetSec = this.parseOffsetSeconds(selected.offset);
        const sourceTime = new Date(Date.now() + offsetSec * 1000);
        timeEl.textContent = this.formatUtcTime(sourceTime) + ' UTC';

        // Constellation mix (only meaningful when GPS/PPS is the primary).
        constEl.innerHTML = '';
        if ((kind === 'gps' || kind === 'pps') && gps && Array.isArray(gps.satellites)) {
            const counts = {};
            for (const s of gps.satellites) {
                if (s.used) counts[s.constellation] = (counts[s.constellation] || 0) + 1;
            }
            const constLabels = {
                GP: 'GPS', SB: 'SBAS', QZ: 'QZSS',
                GL: 'GLONASS', GA: 'Galileo', GB: 'BeiDou',
            };
            const order = ['GP', 'GA', 'GL', 'GB', 'QZ', 'SB'];
            const parts = order
                .filter(c => counts[c])
                .map(c => `<span class="constellation-badge ${c.toLowerCase()}">${constLabels[c]} ×${counts[c]}</span>`);
            constEl.innerHTML = parts.join('');
        }
    },

    updateSourcesTable(sources) {
        const tbody = document.getElementById('sources-tbody');
        if (!sources || sources.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:#5c6078">No source data</td></tr>';
            return;
        }

        const stateColors = {
            '*': 'selected', '+': 'combined', '-': 'not-combined',
            'x': 'error', '~': 'variable', '?': 'unusable',
        };

        // Capture "now" once so every computed source time uses the same
        // reference, otherwise rows would disagree by milliseconds.
        const nowMs = Date.now();

        tbody.innerHTML = sources.map(src => {
            const dotClass = stateColors[src.state] || 'unusable';
            const typeLabel = { '#': 'Refclock', '^': 'Server', '=': 'Peer' }[src.mode] || src.mode;
            const reachBits = src.reach.toString(2).padStart(8, '0');
            const rowClass = src.is_selected ? ' class="source-row-selected"' : '';

            // Per-source UTC time: system time + this source's offset.
            // Only meaningful when the source is reachable; otherwise we've
            // only ever had stale data so show a dash.
            let sourceTimeCell = '-';
            if (src.is_reachable && src.offset) {
                const offsetSec = this.parseOffsetSeconds(src.offset);
                const t = new Date(nowMs + offsetSec * 1000);
                sourceTimeCell = this.formatUtcTime(t);
            }

            return `<tr${rowClass}>
                <td>${typeLabel}</td>
                <td>
                    <span class="source-state">
                        <span class="source-state-dot ${dotClass}"></span>
                        ${src.state_description}
                    </span>
                </td>
                <td>${src.name}</td>
                <td>${src.stratum}</td>
                <td>${sourceTimeCell}</td>
                <td>2<sup>${src.poll}</sup> (${Math.pow(2, src.poll)}s)</td>
                <td title="Binary: ${reachBits}">${src.reach > 0 ? src.reach.toString(8).padStart(3, '0') : '000'}</td>
                <td>${src.last_rx || '-'}</td>
                <td>${src.offset || '-'}</td>
                <td>${src.error || '-'}</td>
            </tr>`;
        }).join('');
    },

    updateGPSD(gpsd, gps) {
        if (!gpsd) return;
        this.setText('gpsd-connected', gpsd.connected ? 'Yes' : 'No');
        document.getElementById('gpsd-connected').className =
            'value ' + (gpsd.connected ? 'good' : 'error');
        this.setText('gpsd-version', gpsd.version || '--');

        if (gpsd.devices && gpsd.devices.length > 0) {
            const devList = gpsd.devices.map(d => {
                const parts = [d.path || 'unknown'];
                if (d.driver) parts.push(`(${d.driver})`);
                return parts.join(' ');
            }).join(', ');
            this.setText('gpsd-devices', devList);
        } else {
            this.setText('gpsd-devices', '--');
        }

        if (gps && gps.meta) {
            this.setText('gpsd-sentences', gps.meta.sentences_parsed || '0');
            this.setText('gpsd-errors', gps.meta.parse_errors || '0');
        }
    },

    setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    },
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => Dashboard.init());
