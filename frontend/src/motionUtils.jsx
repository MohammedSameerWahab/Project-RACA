import { useEffect, useRef, useState } from "react";

/**
 * 7) LERP (Linear Interpolation) function
 */
export function lerp(start, end, amt) {
  return (1 - amt) * start + amt * end;
}

/**
 * 6) Map Function
 * Maps a number from one range to another.
 */
export function mapRange(value, inMin, inMax, outMin, outMax) {
  if (inMax === inMin) return outMin;
  return outMin + ((value - inMin) / (inMax - inMin)) * (outMax - outMin);
}

/**
 * 1) Smooth Scroll & Scroll Tracking (Lenis-style via RAF and LERP)
 */
export function useSmoothScrollTracking() {
  const [scrollY, setScrollY] = useState(0);
  const [scrollProgress, setScrollProgress] = useState(0);

  useEffect(() => {
    let currentScroll = window.scrollY;
    let targetScroll = window.scrollY;
    let rafId = null;

    function handleScroll() {
      targetScroll = window.scrollY;
    }

    function update() {
      // Smooth LERP damping
      currentScroll = lerp(currentScroll, targetScroll, 0.1);
      setScrollY(currentScroll);

      const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
      if (maxScroll > 0) {
        setScrollProgress(Math.min(1, Math.max(0, currentScroll / maxScroll)));
      }

      rafId = requestAnimationFrame(update);
    }

    window.addEventListener("scroll", handleScroll, { passive: true });
    rafId = requestAnimationFrame(update);

    return () => {
      window.removeEventListener("scroll", handleScroll);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, []);

  return { scrollY, scrollProgress };
}

/**
 * 2) Viewport Detection Hook (Intersection Observer API)
 */
export function useInView(options = { threshold: 0.15 }) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setInView(true);
      }
    }, options);

    observer.observe(el);
    return () => observer.disconnect();
  }, [options]);

  return [ref, inView];
}

/**
 * 5) Text Splitting Component
 * Splits words / characters with staggered CSS transition delays
 * for editorial motion typography.
 */
export function SplitText({ text, className = "", delay = 0, charDelay = 0.025 }) {
  const words = text.split(" ");

  return (
    <span className={`split-text-wrapper ${className}`}>
      {words.map((word, wordIndex) => (
        <span key={wordIndex} className="split-word" style={{ display: "inline-block", whiteSpace: "nowrap" }}>
          {word.split("").map((char, charIndex) => {
            const totalIndex = wordIndex * 6 + charIndex;
            return (
              <span
                key={charIndex}
                className="split-char"
                style={{
                  display: "inline-block",
                  transitionDelay: `${delay + totalIndex * charDelay}s`,
                }}
              >
                {char}
              </span>
            );
          })}
          {wordIndex < words.length - 1 && <span className="split-space">&nbsp;</span>}
        </span>
      ))}
    </span>
  );
}
