/**
 * Stencil monogram: a solid tile with an R cut out of it.
 * Color follows the surrounding text, so day mode stays black on beige.
 */
export default function RacaLogo({ size = 34, className = "" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`raca-modern-logo ${className}`}
      aria-hidden="true"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M6 2.5h20A3.5 3.5 0 0 1 29.5 6v20a3.5 3.5 0 0 1-3.5 3.5H6A3.5 3.5 0 0 1 2.5 26V6A3.5 3.5 0 0 1 6 2.5Zm3.6 5.1h8.05c3.72 0 6.25 2.28 6.25 5.62 0 2.62-1.58 4.62-4.02 5.32l5.02 6.86h-4.55l-4.62-6.42h-2.42v6.42H9.6V7.6Zm3.7 3.15v4.7h4.15c1.58 0 2.52-.9 2.52-2.35s-.94-2.35-2.52-2.35h-4.15Z"
      />
    </svg>
  );
}
