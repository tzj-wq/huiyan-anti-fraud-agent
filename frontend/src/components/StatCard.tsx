export function StatCard({ label, value, tone = "blue" }: { label: string; value: string | number; tone?: string }) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
