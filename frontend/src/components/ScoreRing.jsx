const scoreColor = s => s >= 80 ? "#16a34a" : s >= 60 ? "#b45309" : "#dc2626";
const trackColor = "#f0f3f8";

export default function ScoreRing({ score, size = 100 }) {
    const strokeW = size * 0.11;
    const r = (size - strokeW) / 2;
    const circ = 2 * Math.PI * r;
    const fill = (score / 100) * circ;
    const color = scoreColor(score);

    return (
        <div className="score-ring" style={{ width: size, height: size }}>
            <svg width={size} height={size}>
                <circle
                    cx={size / 2} cy={size / 2} r={r}
                    fill="none"
                    stroke={trackColor}
                    strokeWidth={strokeW}
                />
                <circle
                    cx={size / 2} cy={size / 2} r={r}
                    fill="none"
                    stroke={color}
                    strokeWidth={strokeW}
                    strokeDasharray={`${fill} ${circ}`}
                    strokeLinecap="round"
                    style={{ transition: "stroke-dasharray 0.7s cubic-bezier(.4,0,.2,1)" }}
                />
            </svg>
            <div className="score-ring-text">
                <div className="score-num" style={{ color }}>{score}</div>
                <div className="score-max">/100</div>
            </div>
        </div>
    );
}
