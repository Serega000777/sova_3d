export type ExactHoleAxis = "x" | "y" | "z";

const IN_PLANE_AXES: Record<ExactHoleAxis, readonly [string, string]> = {
  x: ["Y", "Z"],
  y: ["X", "Z"],
  z: ["X", "Y"],
};

/** Explain the kernel's absolute model-space coordinates without implying a face-local origin. */
export function exactHoleCoordinateCopy(language: "ru" | "en", axis: ExactHoleAxis) {
  const [uAxis, vAxis] = IN_PLANE_AXES[axis];
  if (language === "ru") {
    return {
      help: `Выберите плоскую грань по мировой нормали. U = мировая ${uAxis}, V = мировая ${vAxis}: это абсолютные координаты в плоскости грани, а не смещения от её центра. Ядро просверлит цилиндрическое отверстие в новой immutable-версии.`,
      uLabel: `Мировая ${uAxis} (U), мм`,
      vLabel: `Мировая ${vAxis} (V), мм`,
    };
  }
  return {
    help: `Choose a planar face by world normal. U = world ${uAxis}, V = world ${vAxis}: these are absolute coordinates in the face plane, not offsets from its centre. The kernel drills a cylindrical hole into a new immutable version.`,
    uLabel: `World ${uAxis} (U), mm`,
    vLabel: `World ${vAxis} (V), mm`,
  };
}
