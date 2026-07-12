import { motion } from "framer-motion";

const DOTS = [0, 1, 2];

export default function Loader({ text = "Procesando..." }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-5"
    >
      {/* Orbiting dots */}
      <div className="relative w-10 h-10">
        {DOTS.map((i) => (
          <motion.span
            key={i}
            className="absolute top-1/2 left-1/2 w-2 h-2 rounded-full bg-p-accent"
            style={{ originX: "50%", originY: "50%" }}
            animate={{ rotate: 360 }}
            transition={{
              duration: 1.4,
              repeat: Infinity,
              ease: "linear",
              delay: i * 0.18,
            }}
            initial={{
              x: `${Math.cos((i / DOTS.length) * Math.PI * 2) * 16 - 4}px`,
              y: `${Math.sin((i / DOTS.length) * Math.PI * 2) * 16 - 4}px`,
            }}
          />
        ))}
      </div>
      <p className="text-sm text-p-text-muted font-medium">{text}</p>
    </div>
  );
}
