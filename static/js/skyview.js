/**
 * Sky View - Polar plot of satellite positions.
 *
 * Renders satellites on a polar projection where:
 * - Center = zenith (90° elevation)
 * - Edge = horizon (0° elevation)
 * - Angle = azimuth (0° = North, clockwise)
 * - Handles negative elevations (below horizon) by clamping to edge
 */

const SkyView = {
    canvas: null,
    ctx: null,
    satellites: [],

    COLORS: {
        GP: '#4a9eff',  // GPS - blue
        SB: '#a78bfa',  // SBAS - purple
        QZ: '#fb923c',  // QZSS - orange
        GL: '#f87171',  // GLONASS - red
        GA: '#34d399',  // Galileo - green
        GB: '#fbbf24',  // BeiDou - yellow
        GI: '#f472b6',  // NavIC - pink
        '??': '#8b8fa3', // Unknown - gray
    },

    CONSTELLATION_NAMES: {
        GP: 'GPS',
        SB: 'SBAS',
        QZ: 'QZSS',
        GL: 'GLONASS',
        GA: 'Galileo',
        GB: 'BeiDou',
        GI: 'NavIC',
    },

    init(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.resize();
        window.addEventListener('resize', () => this.resize());
    },

    resize() {
        const container = this.canvas.parentElement;
        const size = Math.min(container.clientWidth - 20, 400);
        this.canvas.width = size * (window.devicePixelRatio || 1);
        this.canvas.height = size * (window.devicePixelRatio || 1);
        this.canvas.style.width = size + 'px';
        this.canvas.style.height = size + 'px';
        this.ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
        this.draw();
    },

    update(satellites) {
        this.satellites = satellites || [];
        this.draw();
    },

    draw() {
        const ctx = this.ctx;
        const w = this.canvas.width / (window.devicePixelRatio || 1);
        const h = this.canvas.height / (window.devicePixelRatio || 1);
        const cx = w / 2;
        const cy = h / 2;
        const radius = Math.min(cx, cy) - 40;

        ctx.clearRect(0, 0, w, h);

        // Draw concentric circles (elevation rings)
        ctx.strokeStyle = '#2a2d3a';
        ctx.lineWidth = 1;
        for (let elev = 0; elev <= 90; elev += 30) {
            const r = radius * (1 - elev / 90);
            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.stroke();

            // Elevation labels
            if (elev > 0 && elev < 90) {
                ctx.fillStyle = '#5c6078';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(elev + '°', cx + 2, cy - r + 12);
            }
        }

        // Draw cardinal direction lines
        const directions = [
            { label: 'N', angle: -Math.PI / 2 },
            { label: 'E', angle: 0 },
            { label: 'S', angle: Math.PI / 2 },
            { label: 'W', angle: Math.PI },
        ];

        ctx.strokeStyle = '#2a2d3a';
        ctx.lineWidth = 1;
        for (const dir of directions) {
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(
                cx + Math.cos(dir.angle) * radius,
                cy + Math.sin(dir.angle) * radius,
            );
            ctx.stroke();

            // Direction labels
            ctx.fillStyle = '#8b8fa3';
            ctx.font = 'bold 13px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const labelR = radius + 18;
            ctx.fillText(
                dir.label,
                cx + Math.cos(dir.angle) * labelR,
                cy + Math.sin(dir.angle) * labelR,
            );
        }

        // Draw satellites
        for (const sat of this.satellites) {
            // Convert azimuth/elevation to x,y
            // Azimuth: 0=North, clockwise. Canvas: 0=East, counterclockwise
            const azRad = (sat.azimuth - 90) * Math.PI / 180;

            // Elevation to radial distance: 90° = center, 0° = edge
            // Clamp negative elevations to slightly outside the circle
            const elev = Math.max(sat.elevation, -5);
            const r = radius * (1 - Math.max(elev, 0) / 90);

            const x = cx + Math.cos(azRad) * r;
            const y = cy + Math.sin(azRad) * r;

            const color = this.COLORS[sat.constellation] || this.COLORS['??'];
            const dotRadius = sat.used ? 8 : 6;

            // Satellite dot
            ctx.beginPath();
            ctx.arc(x, y, dotRadius, 0, Math.PI * 2);

            if (sat.snr > 0) {
                ctx.fillStyle = color;
                ctx.globalAlpha = 0.3 + 0.7 * Math.min(sat.snr / 45, 1);
            } else {
                ctx.fillStyle = 'transparent';
                ctx.globalAlpha = 1;
            }
            ctx.fill();

            ctx.globalAlpha = 1;
            ctx.strokeStyle = color;
            ctx.lineWidth = sat.used ? 2.5 : 1.5;
            ctx.stroke();

            // PRN label
            ctx.fillStyle = '#e4e6ef';
            ctx.font = '9px ' + (window.getComputedStyle(document.body).fontFamily);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(sat.prn, x, y);

            // Below-horizon indicator
            if (sat.elevation < 0) {
                ctx.strokeStyle = '#5c6078';
                ctx.lineWidth = 1;
                ctx.setLineDash([2, 2]);
                ctx.beginPath();
                ctx.arc(x, y, dotRadius + 3, 0, Math.PI * 2);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }

        // Legend
        const legendY = h - 15;
        let legendX = 10;
        ctx.font = '10px sans-serif';
        const constellationsPresent = [...new Set(this.satellites.map(s => s.constellation))];
        for (const c of constellationsPresent) {
            const color = this.COLORS[c] || this.COLORS['??'];
            const name = this.CONSTELLATION_NAMES[c] || c;

            ctx.fillStyle = color;
            ctx.fillRect(legendX, legendY - 4, 8, 8);
            legendX += 12;

            ctx.fillStyle = '#8b8fa3';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(name, legendX, legendY);
            legendX += ctx.measureText(name).width + 12;
        }
    },
};
