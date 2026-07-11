import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useWizardStore, type FileEntry } from "@/store/useWizardStore";
import { createRound, uploadFile, getMetrics, getRoundResponses } from "@/api/client";
import type { Round } from "@/api/types";

function waitUntilFileDone(fileId: string): Promise<void> {
  const current = useWizardStore
    .getState()
    .files.find((f) => f.id === fileId);
  if (current?.status === "done") return Promise.resolve();

  return new Promise((resolve) => {
    const unsub = useWizardStore.subscribe((state) => {
      const f = state.files.find((fi) => fi.id === fileId);
      if (f?.status === "done") {
        unsub();
        resolve();
      }
    });
  });
}

export function useWizardOrchestrator() {
  const navigate = useNavigate();

  const startProcessing = useCallback(async () => {
    const { files, updateFile, setActiveFileId, showToast, activeStudyId } =
      useWizardStore.getState();

    for (const entry of files) {
      navigate("/project/processing");
      updateFile(entry.id, { status: "classifying" });

      try {
        let roundName = entry.name;
        let round;
        try {
          round = await createRound(roundName, activeStudyId);
        } catch (e) {
          if (e instanceof Error && e.message.includes("409")) {
            roundName = `${entry.name}_${Date.now()}`;
            round = await createRound(roundName, activeStudyId);
          } else {
            throw e;
          }
        }
        updateFile(entry.id, { roundId: round.id, name: roundName });

        const result = await uploadFile(entry.file, entry.column!, round.id);
        updateFile(entry.id, {
          uploadResult: result,
          items: result.items.filter((i) => i.status === "requires_human"),
          status: "reviewing",
        });

        showToast(
          `${result.total} respuestas · ${result.auto_approved} auto · ${result.requires_human} para revisar`,
          "success"
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Error desconocido";
        updateFile(entry.id, { status: "error", errorMessage: msg });
        showToast(`Error en "${entry.name}": ${msg}`, "error");
        return;
      }

      setActiveFileId(entry.id);
      navigate("/project/review");
      await waitUntilFileDone(entry.id);

      const freshEntry = useWizardStore
        .getState()
        .files.find((f) => f.id === entry.id);
      if (freshEntry?.roundId) {
        try {
          const metrics = await getMetrics(freshEntry.roundId);
          updateFile(entry.id, { metrics });
        } catch {
          // Non-critical — dashboard can refresh manually
        }
      }
    }

    navigate("/project/dashboard");
  }, []);

  const advanceToNextFile = useCallback(() => {
    const { files, activeFileId, updateFile } = useWizardStore.getState();
    const entry = files.find((f) => f.id === activeFileId);
    if (entry && entry.status === "reviewing") {
      updateFile(entry.id, { status: "done" });
    }
  }, []);

  const continueRound = useCallback(async (round: Round) => {
    const { setFiles, setActiveFileId, setActiveStudyId, showToast } =
      useWizardStore.getState();

    try {
      const pending = await getRoundResponses(round.id, "requires_human");
      const entry: FileEntry = {
        id: crypto.randomUUID(),
        file: new File([], round.name),
        name: round.name,
        column: null,
        columns: [],
        roundId: round.id,
        uploadResult: {
          round_id: round.id,
          total: round.total ?? pending.length,
          auto_approved: round.auto_approved ?? 0,
          requires_human: pending.length,
          generic: 0,
          items: [],
        },
        items: pending,
        metrics: null,
        status: pending.length > 0 ? "reviewing" : "done",
      };
      setFiles([entry]);
      setActiveFileId(entry.id);
      if (round.study_id) setActiveStudyId(round.study_id);

      if (pending.length > 0) {
        navigate("/project/review");
      } else {
        const metrics = await getMetrics(round.id);
        setFiles([{ ...entry, metrics }]);
        navigate("/project/dashboard");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Error desconocido";
      showToast(`No se pudo continuar el round: ${msg}`, "error");
    }
  }, []);

  const resetWizard = useCallback(() => {
    const { setFiles, setStage, setActiveFileId, setFocusedItemIdx, resetSession } =
      useWizardStore.getState();
    setFiles([]);
    setStage("upload");
    setActiveFileId(null);
    setFocusedItemIdx(0);
    resetSession();
    navigate("/project/upload");
  }, [navigate]);

  return { startProcessing, advanceToNextFile, resetWizard, continueRound };
}
