import { motion } from "framer-motion";

const DOTS = [0, 1, 2];

type LoaderVariant = "orbit" | "pulse" | "stages";

interface LoaderProps {
  text?: string;
  variant?: LoaderVariant;
  progress?: number;
}

export default function Loader({
  text = "Procesando...",
  variant = "orbit",
  progress,
}: LoaderProps) {
  if (variant === "pulse") {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-5">
        <motion.div
          className="relative w-12 h-12"
          animate={{ scale: [1, 1.15, 1] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
        >
          <div className="absolute inset-0 rounded-full bg-p-accent/15" />
          <div className="absolute inset-2 rounded-full bg-p-accent/30" />
          <div className="absolute inset-4 rounded-full bg-p-accent" />
        </motion.div>
        <p className="text-sm text-p-text-muted font-medium">{text}</p>
      </div>
    );
  }

  if (variant === "stages" && progress !== undefined) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-5 px-8">
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
        <p className="text-sm text-p-text-muted font-medium text-center">{text}</p>
        <div className="w-full max-w-xs">
          <div className="h-1.5 rounded-full bg-p-bg-subtle overflow-hidden">
            <motion.div
              className="h-full bg-[linear-gradient(to_right,#5A228B,#FF4D6D,#FF6A33,#FFC300)] rounded-full"
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(progress, 100)}%` }}
              transition={{ duration: 0.6, ease: [0.19, 1, 0.22, 1] }}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-5">
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
