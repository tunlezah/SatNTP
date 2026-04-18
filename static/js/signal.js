/**
 * Signal Strength Chart - Bar chart of satellite SNR values.
 *
 * Displays SNR (Signal-to-Noise Ratio) for each satellite as a vertical bar.
 * Color-coded by constellation. Bars with SNR=0 shown as thin outlines.
 */

const SignalChart = {
    canvas: null,
    ctx: null,
    satellites: [],

    COLORS: {
        GP: '#4a9eff',
        SB: '#a78bfa',
        QZ: '#fb923c',
        GL: '#f87171',
        GA: '#34d399',
        GB: '#fbbf24',
        GI: '#f472b6',
        '??': '#8b8fa3',
    },

    MAX_SNR: 50,  // Maximum expected SNR for scale

    init(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.resize();
        window.addEventListener('resize', () => this.resize());
    },

    resize() {
        const container = this.canvas.parentElement;
        const w = container.clientWidth - 20;
        const h = 280;
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = w * dpr;
        this.canvas.height = h * dpr;
        this.canvas.style.width = w + 'px';
        this.canvas.style.height = h + 'px';
        this.ctx.scale(dpr, dpr);
        this.draw();
    },

    update(satellites) {
        this.satellites = satellites || [];
        this.draw();
    },

    draw() {
        const ctx = this.ctx;
        const dpr = window.devicePixelRatio || 1;
        const w = this.canvas.width / dpr;
        const h = this.canvas.height / dpr;
        const margin = { top: 20, right: 10, bottom: 50, left: 40 };
        const plotW = w - margin.left - margin.right;
        const plotH = h - margin.top - margin.bottom;

        ctx.clearRect(0, 0, w, h);

        if (this.satellites.length === 0) {
            ctx.fillStyle = '#5c6078';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No satellite data', w / 2, h / 2);
            return;
        }

        const n = this.satellites.length;
        const barWidth = Math.min(Math.floor(plotW / n) - 2, 30);
        const gap = Math.max((plotW - barWidth * n) / (n + 1), 1);

        // Y-axis gridlines
        ctx.strokeStyle = '#2a2d3a';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#5c6078';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        for (let snr = 0; snr <= this.MAX_SNR; snr += 10) {
            const y = margin.top + plotH * (1 - snr / this.MAX_SNR);
            ctx.beginPath();
            ctx.moveTo(margin.left, y);
            ctx.lineTo(w - margin.right, y);
            ctx.stroke();
            ctx.fillText(snr.toString(), margin.left - 5, y);
        }

        // Y-axis label
        ctx.save();
        ctx.translate(10, margin.top + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = '#5c6078';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('SNR (dB-Hz)', 0, 0);
        ctx.restore();

        // Draw bars
        for (let i = 0; i < n; i++) {
            const sat = this.satellites[i];
            const x = margin.left + gap + i * (barWidth + gap);
            const color = this.COLORS[sat.constellation] || this.COLORS['??'];

            if (sat.snr > 0) {
                const barH = plotH * Math.min(sat.snr / this.MAX_SNR, 1);
                const y = margin.top + plotH - barH;

                // Bar fill with gradient
                const grad = ctx.createLinearGradient(x, y, x, margin.top + plotH);
                grad.addColorStop(0, color);
                grad.addColorStop(1, color + '40');
                ctx.fillStyle = grad;
                ctx.fillRect(x, y, barWidth, barH);

                // SNR value on top
                ctx.fillStyle = '#e4e6ef';
                ctx.font = '9px monospace';
                ctx.textAlign = 'center';
                ctx.fillText(Math.round(sat.snr), x + barWidth / 2, y - 4);
            } else {
                // Empty bar outline for untracked satellites
                ctx.strokeStyle = color + '40';
                ctx.lineWidth = 1;
                ctx.strokeRect(x, margin.top + plotH - 2, barWidth, 2);
            }

            // PRN label below
            ctx.save();
            ctx.translate(x + barWidth / 2, margin.top + plotH + 8);
            ctx.rotate(n > 15 ? Math.PI / 4 : 0);
            ctx.fillStyle = color;
            ctx.font = '9px sans-serif';
            ctx.textAlign = n > 15 ? 'left' : 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(sat.display_id, 0, 0);
            ctx.restore();
        }
    },
};
