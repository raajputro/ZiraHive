/** The ZiraHive mark: a honeycomb cell holding a smaller one. */
export default function HiveMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
      <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75z" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinejoin="round" />
      <path d="M16 11 20.5 13.5v5L16 21l-4.5-2.5v-5z" fill="currentColor" />
    </svg>
  );
}
