/* Inline icon set. Stroke icons inherit currentColor. */

const s = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

const Svg = ({ children, ...rest }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" {...s} {...rest}>
    {children}
  </svg>
);

export const Mic = (p) => (
  <Svg {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0" />
    <path d="M12 18v3" />
  </Svg>
);
export const Speaker = (p) => (
  <Svg {...p}>
    <path d="M4 10v4h4l5 4V6L8 10H4z" />
    <path d="M16 9a4 4 0 0 1 0 6" />
    <path d="M18.5 6.5a8 8 0 0 1 0 11" />
  </Svg>
);
export const SpeakerOff = (p) => (
  <Svg {...p}>
    <path d="M4 10v4h4l5 4V6L8 10H4z" />
    <path d="M17 9l5 6" />
    <path d="M22 9l-5 6" />
  </Svg>
);
export const Arrow = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M5 12h14" />
    <path d="M13 6l6 6-6 6" />
  </Svg>
);
export const Check = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M5 12.5l4.5 4.5L19 7" />
  </Svg>
);
export const Cross = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M6 6l12 12" />
    <path d="M18 6L6 18" />
  </Svg>
);
export const Plus = (p) => (
  <Svg {...p}>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </Svg>
);
export const Trash = (p) => (
  <Svg {...p}>
    <path d="M4 7h16" />
    <path d="M10 11v6" />
    <path d="M14 11v6" />
    <path d="M6 7l1 13h10l1-13" />
    <path d="M9 7V4h6v3" />
  </Svg>
);
export const Pencil = (p) => (
  <Svg {...p}>
    <path d="M4 20h4L20 8l-4-4L4 16v4z" />
    <path d="M14 6l4 4" />
  </Svg>
);
export const Caret = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M9 5l7 7-7 7" />
  </Svg>
);
export const Play = (p) => (
  <Svg {...p}>
    <path d="M7 4.5v15l13-7.5z" />
  </Svg>
);
export const Pause = (p) => (
  <Svg {...p}>
    <path d="M9 5v14" />
    <path d="M15 5v14" />
  </Svg>
);
export const Stop = (p) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </Svg>
);
export const Timer = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="13" r="8" />
    <path d="M12 9v4l2.5 2.5" />
    <path d="M9 2h6" />
  </Svg>
);
export const Chart = (p) => (
  <Svg {...p}>
    <path d="M4 20h16" />
    <path d="M7 20v-6" />
    <path d="M12 20V8" />
    <path d="M17 20v-9" />
  </Svg>
);
export const Brain = (p) => (
  <Svg {...p}>
    <path d="M12 5a3 3 0 0 0-6 0 3 3 0 0 0-1 5.8A3 3 0 0 0 7 17a3 3 0 0 0 5 2z" />
    <path d="M12 5a3 3 0 0 1 6 0 3 3 0 0 1 1 5.8A3 3 0 0 1 17 17a3 3 0 0 1-5 2z" />
    <path d="M12 5v14" />
  </Svg>
);
export const Upload = (p) => (
  <Svg {...p}>
    <path d="M12 16V4" />
    <path d="M8 8l4-4 4 4" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </Svg>
);
export const Doc = (p) => (
  <Svg {...p}>
    <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
    <path d="M14 3v4h4" />
  </Svg>
);
export const Bulb = (p) => (
  <Svg {...p}>
    <path d="M9 18h6" />
    <path d="M10 21h4" />
    <path d="M12 3a6 6 0 0 0-4 10.5V15h8v-1.5A6 6 0 0 0 12 3z" />
  </Svg>
);
export const Logout = (p) => (
  <Svg {...p}>
    <path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" />
    <path d="M16 16l4-4-4-4" />
    <path d="M20 12H9" />
  </Svg>
);
export const Send = (p) => (
  <Svg {...p}>
    <path d="M4 12l16-8-5 16-3-6-8-2z" />
  </Svg>
);

/* Decorative isometric cubes from the reference theme. */
export const CubeBook = (p) => (
  <svg viewBox="0 0 200 200" width="100%" height="100%" aria-hidden="true" {...p}>
    <polygon points="100,10 182,56 100,102 18,56" fill="#EE6A5F" stroke="#171B2E" strokeWidth="4" />
    <polygon points="18,56 100,102 100,190 18,144" fill="#D8403A" stroke="#171B2E" strokeWidth="4" />
    <polygon points="100,102 182,56 182,144 100,190" fill="#B4322D" stroke="#171B2E" strokeWidth="4" />
    <g stroke="#171B2E" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
      <path d="M64 58 L100 40 L136 58" />
      <path d="M100 40 L100 76" />
      <path d="M64 58 L100 76 L136 58" />
    </g>
    <circle cx="34" cy="66" r="5" fill="#171B2E" />
    <circle cx="166" cy="66" r="5" fill="#171B2E" />
  </svg>
);
export const CubeChat = (p) => (
  <svg viewBox="0 0 200 200" width="100%" height="100%" aria-hidden="true" {...p}>
    <polygon points="100,10 182,56 100,102 18,56" fill="#4C6FE0" stroke="#171B2E" strokeWidth="4" />
    <polygon points="18,56 100,102 100,190 18,144" fill="#3452B4" stroke="#171B2E" strokeWidth="4" />
    <polygon points="100,102 182,56 182,144 100,190" fill="#26398A" stroke="#171B2E" strokeWidth="4" />
    <path
      d="M76 44 h48 a8 8 0 0 1 8 8 v14 a8 8 0 0 1 -8 8 h-30 l-10 10 v-10 h-8 a8 8 0 0 1 -8 -8 v-14 a8 8 0 0 1 8 -8 z"
      fill="#fff" stroke="#171B2E" strokeWidth="3.5" strokeLinejoin="round"
    />
    <circle cx="34" cy="66" r="5" fill="#171B2E" />
    <circle cx="166" cy="66" r="5" fill="#171B2E" />
  </svg>
);
export const CubeCheck = (p) => (
  <svg viewBox="0 0 200 200" width="100%" height="100%" aria-hidden="true" {...p}>
    <polygon points="100,10 182,56 100,102 18,56" fill="#FFE94A" stroke="#171B2E" strokeWidth="4" />
    <polygon points="18,56 100,102 100,190 18,144" fill="#F2C400" stroke="#171B2E" strokeWidth="4" />
    <polygon points="100,102 182,56 182,144 100,190" fill="#D9A800" stroke="#171B2E" strokeWidth="4" />
    <path d="M72 58 L92 76 L130 40" fill="none" stroke="#171B2E" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="34" cy="66" r="5" fill="#171B2E" />
    <circle cx="166" cy="66" r="5" fill="#171B2E" />
  </svg>
);
