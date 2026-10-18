import { getProjectGoal, type CreateScenario } from "@physical-ai/contracts";
import { useRouter } from "expo-router";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { CreateSheet } from "@/src/CreateSheet";

interface CreateFlowValue {
  openCreate: () => void;
  chooseScenario: (scenario: CreateScenario) => void;
}

const CreateFlowContext = createContext<CreateFlowValue | null>(null);

export function CreateFlowProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [sheetOpen, setSheetOpen] = useState(false);

  const chooseScenario = useCallback((scenario: CreateScenario) => {
    setSheetOpen(false);
    const goal = scenario.goal ? getProjectGoal(scenario.goal) : null;
    if (goal?.source === "scan" && goal.scanSubject) {
      router.push(`/scan?subject=${goal.scanSubject}`);
      return;
    }
    if (scenario.id === "import_file") {
      router.push("/import");
      return;
    }
    if (scenario.goal) {
      router.push({ pathname: "/projects", params: { goal: scenario.goal, create: Date.now().toString() } });
    }
  }, [router]);

  const value = useMemo<CreateFlowValue>(() => ({
    openCreate: () => setSheetOpen(true),
    chooseScenario,
  }), [chooseScenario]);

  return (
    <CreateFlowContext.Provider value={value}>
      {children}
      <CreateSheet visible={sheetOpen} onClose={() => setSheetOpen(false)} onChoose={chooseScenario} />
    </CreateFlowContext.Provider>
  );
}

export function useCreateFlow(): CreateFlowValue {
  const value = useContext(CreateFlowContext);
  if (!value) throw new Error("useCreateFlow must be used inside <CreateFlowProvider>");
  return value;
}
