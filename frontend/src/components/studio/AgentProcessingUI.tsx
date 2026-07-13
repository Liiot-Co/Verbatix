import { useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function AgentProcessingUI() {
  const [step, setStep] = useState(0);
  
  const steps = [
    "Normalizando y limpiando registros...",
    "Motor Fuzzy cruzando histórico...",
    "Agente LLM evaluando casos atípicos...",
    "Encontrando patrones semánticos...",
    "Construyendo libro de códigos final..."
  ];

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % steps.length);
    }, 2500);
    return () => clearInterval(id);
  }, []); // steps is static

  return (
    <div className="flex flex-col items-center justify-center py-20 space-y-8">
      <div className="relative flex items-center justify-center">
        <motion.div
          animate={{ scale: [1, 1.5, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
          className="absolute w-28 h-28 rounded-full bg-p-accent blur-xl pointer-events-none"
        />
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
          className="relative w-16 h-16 rounded-full border-[3px] border-p-surface border-t-p-accent flex items-center justify-center bg-p-surface"
        >
          <motion.div animate={{ rotate: -360 }} transition={{ duration: 4, repeat: Infinity, ease: "linear" }}>
             <Bot className="w-7 h-7 text-p-accent" />
          </motion.div>
        </motion.div>
      </div>
      <div className="space-y-2 text-center">
        <h3 className="text-xl font-heading font-semibold text-p-text tracking-tight">Agente en ejecución</h3>
        <div className="h-6 overflow-hidden">
          <AnimatePresence mode="wait">
            <motion.p
              key={step}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3 }}
              className="text-sm font-mono text-p-text-muted"
            >
              <span className="text-p-accent mr-2">➜</span>
              {steps[step]}
            </motion.p>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
