"use client";

interface Props {
  src: string;
  label: string;
}

export function VideoPlayer({ src, label }: Props) {
  return (
    <div
      className="w-full rounded-xl overflow-hidden"
      style={{ background: "#0a0a0a", aspectRatio: "16/9", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.06)" }}
    >
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        src={src}
        controls
        playsInline
        preload="auto"
        className="w-full h-full object-contain"
        aria-label={label}
        style={{ display: "block", background: "#000" }}
      />
    </div>
  );
}
