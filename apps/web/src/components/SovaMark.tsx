export function SovaMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M16 2.75 27.47 9.38v13.24L16 29.25 4.53 22.62V9.38L16 2.75Z"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="16" r="5.2" stroke="currentColor" strokeWidth="2.4" />
      <path d="m22.3 8.9 3.05 1.76" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
