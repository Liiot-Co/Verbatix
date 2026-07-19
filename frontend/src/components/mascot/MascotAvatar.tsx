import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion, useSpring, type MotionValue } from "framer-motion";
import { PRESENCE_CATALOG, type PresenceStatus } from "@/lib/presence";

interface MascotAvatarProps {
  status: PresenceStatus;
  size: "sm" | "lg";
  onClick: () => void;
  hint?: boolean;
  title?: string | undefined;
}

const EYE_PATCH = { x: 365, y: 410, width: 440, height: 185, rx: 86 };

type AnimatedStatus = Exclude<PresenceStatus, "disponible">;

const FACE_WINDOWS: Record<AnimatedStatus, {
  viewBox: string;
  fill: string;
  patch: { x: number; y: number; width: number; height: number; rx: number };
  leftEye: { x: number; y: number; rx: number; ry: number };
  rightEye: { x: number; y: number; rx: number; ry: number };
  mouth?: { x: number; y: number; width: number };
}> = {
  almorzando: {
    viewBox: "0 0 1254 1254", fill: "#101426",
    patch: { x: 258, y: 568, width: 370, height: 122, rx: 44 },
    leftEye: { x: 324, y: 616, rx: 42, ry: 54 }, rightEye: { x: 572, y: 620, rx: 42, ry: 54 },
    mouth: { x: 448, y: 663, width: 38 },
  },
  en_el_bano: {
    viewBox: "0 0 1254 1254", fill: "#1F1E2D",
    patch: { x: 448, y: 454, width: 395, height: 166, rx: 56 },
    leftEye: { x: 517, y: 540, rx: 43, ry: 55 }, rightEye: { x: 778, y: 541, rx: 43, ry: 55 },
  },
  en_break: {
    viewBox: "0 0 1254 1254", fill: "#201F2D",
    patch: { x: 474, y: 470, width: 350, height: 126, rx: 50 },
    leftEye: { x: 534, y: 514, rx: 40, ry: 51 }, rightEye: { x: 765, y: 529, rx: 40, ry: 51 },
    mouth: { x: 645, y: 565, width: 38 },
  },
  en_reunion: {
    viewBox: "0 0 1227 1281", fill: "#272636",
    patch: { x: 460, y: 526, width: 282, height: 118, rx: 48 },
    leftEye: { x: 514, y: 588, rx: 34, ry: 43 }, rightEye: { x: 692, y: 586, rx: 34, ry: 43 },
    mouth: { x: 602, y: 620, width: 30 },
  },
};

function FaceExpression({
  status,
  blink,
  pupilX,
  pupilY,
  eyeScale,
  hovered,
}: {
  status: AnimatedStatus;
  blink: number;
  pupilX: MotionValue<number>;
  pupilY: MotionValue<number>;
  eyeScale: MotionValue<number>;
  hovered: boolean;
}) {
  const face = FACE_WINDOWS[status];
  const eyeCenterX = (face.leftEye.x + face.rightEye.x) / 2;
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={face.viewBox} aria-hidden="true">
      <rect {...face.patch} fill={face.fill} />
      <motion.g
        style={{ scaleY: blink, transformOrigin: `${eyeCenterX}px ${face.leftEye.y}px` }}
        animate={hovered ? { scale: 1.08, y: -4 } : { scale: [1, 1.025, 1], y: [0, -2, 0] }}
        transition={hovered ? { type: "spring", stiffness: 260, damping: 20 } : { duration: 3.8, repeat: Infinity, ease: "easeInOut" }}
      >
        <motion.ellipse
            cx={face.leftEye.x}
            cy={face.leftEye.y}
            rx={face.leftEye.rx}
            ry={face.leftEye.ry}
            fill="#F8F8F8"
            style={{ scale: eyeScale }}
          />
        <motion.ellipse
            cx={face.rightEye.x}
            cy={face.rightEye.y}
            rx={face.rightEye.rx}
            ry={face.rightEye.ry}
            fill="#F8F8F8"
            style={{ scale: eyeScale }}
          />
        <motion.g style={{ x: pupilX, y: pupilY }}>
          <ellipse
            cx={face.leftEye.x}
            cy={face.leftEye.y + 4}
            rx={face.leftEye.rx * 0.36}
            ry={face.leftEye.ry * 0.38}
            fill={face.fill}
          />
          <ellipse
            cx={face.rightEye.x}
            cy={face.rightEye.y + 4}
            rx={face.rightEye.rx * 0.36}
            ry={face.rightEye.ry * 0.38}
            fill={face.fill}
          />
        </motion.g>
        {face.mouth && (
          <motion.path
            d={`M${face.mouth.x - face.mouth.width} ${face.mouth.y} Q${face.mouth.x} ${face.mouth.y + 18} ${face.mouth.x + face.mouth.width} ${face.mouth.y}`}
            fill="none"
            stroke="#F8F8F8"
            strokeWidth="12"
            strokeLinecap="round"
            animate={{ scaleX: [1, 1.12, 1] }}
            transition={{ duration: 2.8, repeat: Infinity, ease: "easeInOut" }}
            style={{ transformOrigin: `${face.mouth.x}px ${face.mouth.y}px` }}
          />
        )}
      </motion.g>
    </svg>
  );
}

function SceneMotion({ status }: { status: PresenceStatus }) {
  const loop = { repeat: Infinity, ease: "easeInOut" as const };
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1254 1254" aria-hidden="true">
      {status === "disponible" && <>
        <motion.path d="M301 424l10 25 25 10-25 10-10 25-10-25-25-10 25-10z" fill="#9678F4" animate={{ rotate: [0, 18, 0, -18, 0], scale: [0.85, 1.1, 0.85] }} transition={{ duration: 2.6, ...loop }} style={{ transformOrigin: "301px 449px" }} />
        <motion.path d="M900 565l7 18 18 7-18 7-7 18-7-18-18-7 18-7z" fill="#9678F4" animate={{ rotate: [0, -22, 0, 22, 0], scale: [1, 0.72, 1] }} transition={{ duration: 2.1, ...loop }} style={{ transformOrigin: "900px 583px" }} />
      </>}
      {status === "almorzando" && <>
        {[0, 1, 2].map((crumb) => <motion.circle key={crumb} cx={680 + crumb * 23} cy="550" r="8" fill="#FE5902" animate={{ y: [0, 28, 42], opacity: [0, 1, 0] }} transition={{ duration: 1.8, delay: crumb * 0.34, repeat: Infinity, ease: "easeIn" }} />)}
      </>}
    </svg>
  );
}

export default function MascotAvatar({ status, size, onClick, hint = false, title }: MascotAvatarProps) {
  const reducedMotion = useReducedMotion();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const animationFrame = useRef<number | null>(null);
  const [hovered, setHovered] = useState(false);
  const pupilX = useSpring(0, { stiffness: 180, damping: 20 });
  const pupilY = useSpring(0, { stiffness: 180, damping: 20 });
  const eyeScale = useSpring(1, { stiffness: 280, damping: 22 });
  const [blink, setBlink] = useState(1);
  const meta = PRESENCE_CATALOG[status];
  const dimension = size === "sm" ? "2.75rem" : "8rem";
  const gestureProps = reducedMotion
    ? {}
    : { whileHover: { scale: 1.04, rotate: 1.5 }, whileTap: { scale: 0.94 } };

  useEffect(() => {
    eyeScale.set(hovered && !reducedMotion ? 1.08 : 1);
  }, [eyeScale, hovered, reducedMotion]);

  useEffect(() => {
    if (reducedMotion) return;
    let timer: number | undefined;
    let cancelled = false;
    const blinkOnce = () => {
      setBlink(0.08);
      window.setTimeout(() => setBlink(1), 120);
    };
    const schedule = () => {
      timer = window.setTimeout(() => {
        blinkOnce();
        if (Math.random() < 0.18) window.setTimeout(blinkOnce, 240);
        if (!cancelled) schedule();
      }, 1900 + Math.random() * 2600);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [reducedMotion, status]);

  useEffect(() => {
    if (reducedMotion) return;
    let lastNear = 0;
    const lookAt = (clientX: number, clientY: number) => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const dx = clientX - (rect.left + rect.width / 2);
      const dy = clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(dx, dy);
      if (distance <= 400) {
        lastNear = Date.now();
        const amount = Math.min(15, distance / 12);
        pupilX.set((dx / Math.max(distance, 1)) * amount);
        pupilY.set((dy / Math.max(distance, 1)) * amount);
      }
    };
    const onPointerMove = (event: PointerEvent) => {
      if (animationFrame.current !== null) return;
      animationFrame.current = window.requestAnimationFrame(() => {
        animationFrame.current = null;
        lookAt(event.clientX, event.clientY);
      });
    };
    const idle = window.setInterval(() => {
      if (Date.now() - lastNear < 4000) return;
      pupilX.set((Math.random() - 0.5) * 12);
      pupilY.set((Math.random() - 0.5) * 8);
    }, 4000);
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.clearInterval(idle);
      if (animationFrame.current !== null) window.cancelAnimationFrame(animationFrame.current);
    };
  }, [pupilX, pupilY, reducedMotion, status]);

  return (
    <motion.button
      ref={buttonRef}
      type="button"
      onClick={onClick}
      onHoverStart={() => setHovered(true)}
      onHoverEnd={() => setHovered(false)}
      aria-label={`Cambiar estado — actualmente ${meta.label}`}
      title={title}
      {...gestureProps}
      className={`mascot-avatar relative block shrink-0 rounded-full focus-visible:outline-none ${hint ? "mascot-hint" : ""}`}
      style={{ width: dimension, height: dimension }}
    >
      <motion.span
        className="relative block h-full w-full"
        animate={size === "lg" && !reducedMotion ? { y: [0, -3, 0] } : { y: 0 }}
        transition={size === "lg" && !reducedMotion ? { duration: 4, repeat: Infinity, ease: "easeInOut" } : { duration: 0.16 }}
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.img
            key={status}
            src={meta.art}
            alt=""
            draggable={false}
            initial={{ opacity: 0, scale: reducedMotion ? 1 : 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: reducedMotion ? 1 : 0.92 }}
            transition={reducedMotion ? { duration: 0.18 } : { type: "spring", stiffness: 380, damping: 26 }}
            className="absolute inset-0 h-full w-full select-none object-contain"
          />
        </AnimatePresence>
        {status === "disponible" && (
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1254 1254" aria-hidden="true">
            <rect {...EYE_PATCH} fill="#1F1E2D" />
            <motion.g
              style={{ scaleY: blink, transformOrigin: "627px 505px" }}
              animate={reducedMotion ? { scale: 1, y: 0 } : hovered ? { scale: 1.08, y: -4 } : { scale: [1, 1.025, 1], y: [0, -2, 0] }}
              transition={hovered ? { type: "spring", stiffness: 260, damping: 20 } : { duration: 3.8, repeat: Infinity, ease: "easeInOut" }}
            >
              <motion.ellipse cx="490" cy="505" rx="51" ry="65" fill="#FDFDFC" style={{ scale: eyeScale }} />
              <motion.ellipse cx="680" cy="505" rx="51" ry="65" fill="#FDFDFC" style={{ scale: eyeScale }} />
              <motion.g style={{ x: pupilX, y: pupilY }}>
                <ellipse cx="490" cy="510" rx="18" ry="25" fill="#1F1E2D" />
                <ellipse cx="680" cy="510" rx="18" ry="25" fill="#1F1E2D" />
              </motion.g>
            </motion.g>
          </svg>
        )}
        {status !== "disponible" && !reducedMotion && (
          <FaceExpression
            status={status}
            blink={blink}
            pupilX={pupilX}
            pupilY={pupilY}
            eyeScale={eyeScale}
            hovered={hovered}
          />
        )}
        {!reducedMotion && size === "lg" && <SceneMotion status={status} />}
      </motion.span>
      {size === "sm" && <span className={`absolute bottom-[3%] right-[3%] h-[22%] w-[22%] rounded-full border-2 border-p-surface ${meta.dotClass}`} />}
    </motion.button>
  );
}
