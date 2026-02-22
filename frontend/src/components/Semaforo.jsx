const map = {
    verde: { label: "Verde", cls: "verde" },
    amarillo: { label: "Amarillo", cls: "amarillo" },
    rojo: { label: "Rojo", cls: "rojo" },
};

export default function Semaforo({ estado }) {
    const { label, cls } = map[estado] || map.rojo;
    return (
        <span className={`semaforo ${cls}`}>
            <span className="dot" />
            {label}
        </span>
    );
}
