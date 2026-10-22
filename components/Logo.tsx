/**
 * Логотип AdaptENG: синяя плашка с белой «A» + словесный знак.
 *
 * Без градиентов фиолетово-розовой гаммы: только синий/небесный.
 */
export default function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={`flex items-center gap-2.5 ${className}`}>
      <svg width="34" height="34" viewBox="0 0 34 34" role="img" aria-label="AdaptENG">
        <defs>
          <linearGradient id="adapteng-logo" x1="0" y1="0" x2="34" y2="34" gradientUnits="userSpaceOnUse">
            <stop stopColor="#1d4ed8" />
            <stop offset="1" stopColor="#38bdf8" />
          </linearGradient>
        </defs>
        <rect width="34" height="34" rx="10" fill="url(#adapteng-logo)" />
        <path
          d="M10.2 24.2 17 9.8l6.8 14.4"
          fill="none"
          stroke="#ffffff"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M13.2 20.1h7.6" stroke="#ffffff" strokeWidth="2.6" strokeLinecap="round" />
      </svg>
      <span className="text-lg font-bold tracking-tight text-slate-900">
        Adapt<span className="text-blue-600">ENG</span>
      </span>
    </span>
  );
}
