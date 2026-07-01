type Item = { label: string; value: string | number; tone?: "default" | "warn" | "danger" | "ok" };

export default function StatCards({ items }: { items: Item[] }) {
  return (
    <div className="stat-cards">
      {items.map((it) => (
        <div key={it.label} className={`stat-card${it.tone ? ` ${it.tone}` : ""}`}>
          <div className="stat-value">{it.value}</div>
          <div className="stat-label">{it.label}</div>
        </div>
      ))}
    </div>
  );
}
