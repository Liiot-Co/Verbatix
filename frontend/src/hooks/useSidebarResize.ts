import { useState, useEffect, useCallback } from "react";

export function useSidebarResize(defaultWidth = 460, minWidth = 300, maxWidth = 800) {
  const [width, setWidth] = useState(defaultWidth);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    if (!isResizing) return;
    const onMouseMove = (e: MouseEvent) => {
      setWidth((w) => Math.max(minWidth, Math.min(maxWidth, w - e.movementX)));
    };
    const onMouseUp = () => setIsResizing(false);
    
    // add a class to body to prevent text selection while resizing
    document.body.classList.add("select-none");
    document.body.style.cursor = "col-resize";
    
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      document.body.classList.remove("select-none");
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [isResizing, minWidth, maxWidth]);

  const startResizing = useCallback(() => {
    setIsResizing(true);
  }, []);

  return { width, isResizing, startResizing };
}
