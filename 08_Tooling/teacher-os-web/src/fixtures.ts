/** Immutable, privacy-safe illustrative lesson data. NOT a Notion/Drive projection. */
export type MaterialKind = "unit" | "worksheet" | "slides";
export type Material = Readonly<{ id: string; kind: MaterialKind; title: string; summary: string; preview: readonly string[] }>;
export type Unit = Readonly<{ id: string; title: string; materials: readonly Material[] }>;
export type Course = Readonly<{ id: string; title: string; grade: 9 | 10; units: readonly Unit[] }>;
export const schoolYears = ["2026–27", "2025–26"] as const;
const photographyMaterials: readonly Material[] = [
  { id: "photo-unit", kind: "unit", title: "Unit Overview", summary: "Rule of Thirds, visual balance and reflection", preview: ["Explore composition", "Compare two images", "Create a photograph", "Reflect on choices"] },
  { id: "photo-worksheet", kind: "worksheet", title: "Composition Worksheet", summary: "Rule of Thirds comparison practice", preview: ["Name the focal point in each photo.", "Which placement creates more visual balance?", "Sentence starter: In Photo __, I notice __."] },
  { id: "photo-slides", kind: "slides", title: "Rule of Thirds Slides", summary: "Modeling and guided practice", preview: ["Slide 1: What is composition?", "Slide 2: Thirds grid and focal point", "Slide 3: Compare two compositions"] },
];
const designMaterials: readonly Material[] = [
  { id: "design-unit", kind: "unit", title: "Unit Overview", summary: "Contrast, alignment and hierarchy", preview: ["Observe graphic layouts", "Identify visual hierarchy", "Make a composition"] },
  { id: "design-worksheet", kind: "worksheet", title: "Design Worksheet", summary: "Compare visual hierarchy", preview: ["Which title stands out first?", "Describe how contrast guides your eye."] },
  { id: "design-slides", kind: "slides", title: "Design Slides", summary: "Examples and practice", preview: ["Slide 1: Visual hierarchy", "Slide 2: Contrast", "Slide 3: Practice"] },
];
export const courses: readonly Course[] = [
  { id: "media1", title: "Digital Media 1", grade: 9, units: [
    { id: "photography", title: "Photography Foundations", materials: photographyMaterials },
    { id: "graphic", title: "Graphic Design Basics", materials: designMaterials },
  ] },
  { id: "media2", title: "Digital Media 2", grade: 10, units: [
    { id: "portfolio", title: "Photography Portfolio", materials: photographyMaterials },
    { id: "storytelling", title: "Visual Storytelling", materials: designMaterials },
  ] },
];
export function selectCourse(id: string): Course | undefined { return courses.find(c => c.id === id); }
export function selectUnit(course: Course, id: string): Unit | undefined { return course.units.find(u => u.id === id); }
export function selectMaterial(unit: Unit, id: string): Material | undefined { return unit.materials.find(m => m.id === id); }
