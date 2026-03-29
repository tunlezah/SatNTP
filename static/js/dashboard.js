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

    updateSourcesTable(sources) {
        const tbody = document.getElementById('sources-tbody');
        if (!sources || sources.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#5c6078">No source data</td></tr>';
            return;
        }

        const stateColors = {
            '*': 'selected', '+': 'combined', '-': 'not-combined',
            'x': 'error', '~': 'variable', '?': 'unusable',
        };

        tbody.innerHTML = sources.map(src => {
            const dotClass = stateColors[src.state] || 'unusable';
            const typeLabel = { '#': 'Refclock', '^': 'Server', '=': 'Peer' }[src.mode] || src.mode;
            const reachBits = src.reach.toString(2).padStart(8, '0');

            return `<tr>
                <td>${typeLabel}</td>
                <td>
                    <span class="source-state">
                        <span class="source-state-dot ${dotClass}"></span>
                        ${src.state_description}
                    </span>
                </td>
                <td>${src.name}</td>
                <td>${src.stratum}</td>
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
