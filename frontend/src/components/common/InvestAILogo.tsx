/**
 * InvestAILogo Component for InvestAI Enterprise.
 * Institutional vector isotype: octagonal quant shield with precision bars and a
 * Markowitz efficient-frontier curve ending in a highlighted optimal-portfolio node.
 */

import type React from "react";
import { useId } from "react";

export type InvestAILogoSize = "sm" | "md" | "lg";

const SIZE_PX: Record<InvestAILogoSize, number> = {
  sm: 24,
  md: 36,
  lg: 64,
};

interface InvestAILogoProps {
  size?: InvestAILogoSize;
  className?: string;
  title?: string;
}

export const InvestAILogo: React.FC<InvestAILogoProps> = ({
  size = "md",
  className,
  title = "InvestAI Enterprise",
}) => {
  const uid = useId();
  const shieldId = `${uid}-shield`;
  const glowId = `${uid}-glow`;
  const titleId = `${uid}-title`;
  const px = SIZE_PX[size];

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 48 48"
      width={px}
      height={px}
      role="img"
      aria-labelledby={titleId}
      className={className}
    >
      <title id={titleId}>{title}</title>
      <defs>
        <linearGradient id={shieldId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0284c7" />
          <stop offset="55%" stopColor="#10b981" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
        <radialGradient id={glowId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Subtle glow ring */}
      <circle
        cx="24"
        cy="24"
        r="23"
        fill="none"
        stroke={`url(#${shieldId})`}
        strokeWidth="1"
        opacity="0.4"
      />

      {/* Octagonal quant shield */}
      <polygon points="17,5 31,5 43,17 43,31 31,43 17,43 5,31 5,17" fill={`url(#${shieldId})`} />
      <polygon
        points="17.8,7 30.2,7 41,17.8 41,30.2 30.2,41 17.8,41 7,30.2 7,17.8"
        fill="#020617"
        opacity="0.28"
      />

      {/* Ascending precision bars */}
      <rect x="13" y="28" width="4.5" height="7" rx="1" fill="#ffffff" opacity="0.85" />
      <rect x="20" y="24" width="4.5" height="11" rx="1" fill="#ffffff" opacity="0.9" />
      <rect x="27" y="20" width="4.5" height="15" rx="1" fill="#ffffff" opacity="0.95" />

      {/* Markowitz efficient frontier */}
      <path
        d="M11 29 C 14 17, 24 12.5, 35 13"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2"
        strokeLinecap="round"
      />

      {/* Optimal portfolio node */}
      <circle cx="35" cy="13" r="5.5" fill={`url(#${glowId})`} />
      <circle cx="35" cy="13" r="2.3" fill="#ffffff" />
    </svg>
  );
};
