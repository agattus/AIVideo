type IconProps = { size?: number; className?: string };

function base({ size = 24, className }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "currentColor",
    className,
    "aria-hidden": true as const,
  };
}

export function IconMenu(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z" />
    </svg>
  );
}

export function IconHome(p: IconProps & { filled?: boolean }) {
  return (
    <svg {...base(p)}>
      {p.filled ? (
        <path d="M4 21V9l8-6 8 6v12h-6v-7h-4v7H4z" />
      ) : (
        <path d="M12 4.33 19 9.5V20h-5v-6H10v6H5V9.5l7-5.17M12 3 4 9v12h7v-6h2v6h7V9l-8-6z" />
      )}
    </svg>
  );
}

export function IconShorts(p: IconProps & { filled?: boolean }) {
  return (
    <svg {...base(p)}>
      {p.filled ? (
        <path d="M10 14.65v-5.3L15 12l-5 2.65zm7.77-4.33-1.2-.5L18 9.06c1.84-.96 2.55-3.3 1.6-5.14s-3.3-2.55-5.14-1.6L13.2 2.9l-.5-1.2C12.08-.24 9.74-.95 7.9 0S5.35 3.3 6.3 5.14l.5 1.2-1.24.58c-1.84.96-2.55 3.3-1.6 5.14s3.3 2.55 5.14 1.6l1.24-.58.5 1.2c.96 1.84 3.3 2.55 5.14 1.6s2.55-3.3 1.6-5.14l-.5-1.2 1.2-.5z" />
      ) : (
        <path d="m17.77 10.32-1.2-.5L18 9.06c1.84-.96 2.55-3.3 1.6-5.14s-3.3-2.55-5.14-1.6L13.2 2.9l-.5-1.2C12.08-.24 9.74-.95 7.9 0S5.35 3.3 6.3 5.14l.5 1.2-1.24.58c-1.84.96-2.55 3.3-1.6 5.14s3.3 2.55 5.14 1.6l1.24-.58.5 1.2c.96 1.84 3.3 2.55 5.14 1.6s2.55-3.3 1.6-5.14l-.5-1.2 1.2-.5zm-5.35 3.33-2.9-1.58v3.15l2.9-1.57zm2.9-6.73-1.15.64 2.9 1.58V8.1l-1.75-.95zm-7.5 2.47 1.15-.64L7.07 7.17v1.58l1.75.95zm1.15 5.84 1.15-.64-2.9-1.58v1.58l1.75.64zm6.35-1.58-1.15.64 1.75.95v-1.58l-1.75-.01zM10 14.65v-5.3L15 12l-5 2.65z" />
      )}
    </svg>
  );
}

export function IconSubscriptions(p: IconProps & { filled?: boolean }) {
  return (
    <svg {...base(p)}>
      {p.filled ? (
        <path d="M20 7H4V6h16v1zm2 2v12H2V9h20zm-7 6-5-3v6l5-3zM17 3H7v1h10V3z" />
      ) : (
        <path d="M10 18v-6l5 3-5 3zm9-13H5v1h14V5zm3 3H2v12h20V8zm-2 10H4V10h16v8zM17 3H7v1h10V3z" />
      )}
    </svg>
  );
}

export function IconYou(p: IconProps & { filled?: boolean }) {
  return (
    <svg {...base(p)}>
      {p.filled ? (
        <path d="M3 5v14h18V5H3zm6 12H7v-2h2v2zm0-4H7v-2h2v2zm0-4H7V7h2v2zm4 8h-2v-2h2v2zm0-4h-2v-2h2v2zm0-4h-2V7h2v2zm4 8h-2v-2h2v2zm0-4h-2v-2h2v2zm0-4h-2V7h2v2z" />
      ) : (
        <path d="M4 6h16v12H4V6zm0-2v16h16V4H4zm2 4h2v2H6V8zm0 4h2v2H6v-2zm0 4h2v2H6v-2zm4-8h2v2h-2V8zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm4-8h2v2h-2V8zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z" />
      )}
    </svg>
  );
}

export function IconCreate(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M14 13h-3v3H9v-3H6v-2h3V8h2v3h3v2zm3-7H3v12h14v-6.39l4 1.83V8.56l-4 1.83V6zm0-1v3.55L21 7v7l-4-1.83V19H2V5h15z" />
    </svg>
  );
}

export function IconSearch(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
    </svg>
  );
}

export function IconMic(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15a.998.998 0 0 0-.98-.85c-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z" />
    </svg>
  );
}

export function IconBell(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M10 20h4c0 1.1-.9 2-2 2s-2-.9-2-2zm10-2.65V19H4v-1.65l2-1.88v-5.15C6 6.4 8.63 3.72 12 3v-.75c0-.41.34-.75.75-.75s.75.34.75.75V3c3.37.72 6 3.4 6 7.32v5.15l2 1.88z" />
    </svg>
  );
}

export function IconHistory(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.95 8.95 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z" />
    </svg>
  );
}

export function IconPlaylist(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M14 10H2v2h12v-2zm0-4H2v2h12V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM2 16h8v-2H2v2z" />
    </svg>
  );
}

export function IconLiked(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z" />
    </svg>
  );
}

export function IconWatchLater(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M14.97 16.95 10 13.47V7h2v5.53l4.03 2.43-1.06 1.99zM12 3c-4.96 0-9 4.04-9 9s4.04 9 9 9 9-4.04 9-9-4.04-9-9-9m0-1c5.52 0 10 4.48 10 10s-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2z" />
    </svg>
  );
}

export function IconLike(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M18.77 11h-4.23l1.52-4.94C16.38 5.03 15.54 4 14.38 4c-.58 0-1.14.24-1.52.65L7 11H3v10h4h1h9.43c1.06 0 1.98-.67 2.19-1.61l1.34-6A2 2 0 0 0 18.77 11zM7 20H4v-8h3v8zm12.98-6.61L18.64 19H8v-8.61l5.6-6.06c.05-.05.28-.1.4-.1.31 0 .59.23.65.53l-1.66 5.4h6.78c.28 0 .5.22.5.5l-.12.89z" />
    </svg>
  );
}

export function IconDislike(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M17 4h-1H6.57C5.5 4 4.59 4.67 4.38 5.61l-1.34 6A2 2 0 0 0 5.23 14h4.23l-1.52 4.94C7.62 19.97 8.46 21 9.62 21c.58 0 1.14-.24 1.52-.65L17 14h4V4h-4zM10.4 19.67c-.05.05-.28.1-.4.1-.31 0-.59-.23-.65-.53l1.66-5.4H4.23c-.28 0-.5-.22-.5-.5l.12-.89L5.36 6H16v8.61l-5.6 6.06zM20 13h-3V5h3v8z" />
    </svg>
  );
}

export function IconShare(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M15 5.63 20.66 12 15 18.37V14h-1c-3.96 0-7.14 1-9.72 3.15 1.1-3.96 4.05-7.7 9.72-8.72V5.63M14 3v6C6.22 10.13 3.11 15.33 2 21c2.78-3.97 6.44-6 12-6v6l8-9-8-9z" />
    </svg>
  );
}

export function IconMore(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M7.5 12c0 .83-.67 1.5-1.5 1.5S4.5 12.83 4.5 12s.67-1.5 1.5-1.5 1.5.67 1.5 1.5zm4.5-1.5c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5zm6 0c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5z" />
    </svg>
  );
}

export function IconVerified(p: IconProps) {
  return (
    <svg {...base({ ...p, size: p.size ?? 14 })}>
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm-1.9 14.7L6 12.6l1.5-1.5 2.6 2.6 6-6.1L17.6 9l-7.5 7.7z" />
    </svg>
  );
}

export function IconClose(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M18.3 5.71 12 12.01l-6.3-6.3-1.4 1.42 6.3 6.29-6.3 6.3 1.42 1.4 6.29-6.3 6.3 6.3 1.4-1.42-6.3-6.29 6.3-6.3z" />
    </svg>
  );
}

export function IconPlay(p: IconProps) {
  return (
    <svg {...base(p)}>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
