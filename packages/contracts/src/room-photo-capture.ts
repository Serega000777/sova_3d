/** Item 34: bounded four-wall photo-room capture without LiDAR. */
export type RoomPhotoSectionId = "front" | "right" | "back" | "left";

export interface RoomPhotoSection {
  id: RoomPhotoSectionId;
  titleRu: string;
  guidanceRu: string;
  targetFrames: number;
}

export const ROOM_PHOTO_SECTIONS: readonly RoomPhotoSection[] = [
  { id: "front", titleRu: "Стена 1", guidanceRu: "Пройдите вдоль первой стены; захватите левый и правый углы.", targetFrames: 8 },
  { id: "right", titleRu: "Стена 2", guidanceRu: "Начните с общего угла и снимите вторую стену с перекрытием.", targetFrames: 8 },
  { id: "back", titleRu: "Стена 3", guidanceRu: "Снимите проёмы и оба угла третьей стены.", targetFrames: 8 },
  { id: "left", titleRu: "Стена 4", guidanceRu: "Замкните обход, повторив часть первой стены.", targetFrames: 8 },
];

export type RoomPhotoSectionCounts = Record<RoomPhotoSectionId, number>;

export function emptyRoomPhotoSectionCounts(): RoomPhotoSectionCounts {
  return { front: 0, right: 0, back: 0, left: 0 };
}

export function uncoveredRoomPhotoSections(counts: RoomPhotoSectionCounts): RoomPhotoSection[] {
  return ROOM_PHOTO_SECTIONS.filter((section) => counts[section.id] < section.targetFrames);
}

export function roomPhotoCoveragePercent(counts: RoomPhotoSectionCounts): number {
  const covered = ROOM_PHOTO_SECTIONS.reduce(
    (sum, section) => sum + Math.min(Math.max(counts[section.id], 0), section.targetFrames),
    0,
  );
  const target = ROOM_PHOTO_SECTIONS.reduce((sum, section) => sum + section.targetFrames, 0);
  return Math.round((covered / target) * 100);
}
