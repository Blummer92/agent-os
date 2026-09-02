export type SequenceFrame = Readonly<{
  imageNumber: number;
  preservedState: readonly string[];
  changedState: readonly string[];
}>;

export type SequenceFidelityResult = Readonly<{
  status: 'pass' | 'manual-review';
  reasonCodes: readonly string[];
}>;

export function evaluateSequenceFidelity(frames: readonly SequenceFrame[]): SequenceFidelityResult {
  if (frames.length < 2) return { status: 'manual-review', reasonCodes: ['sequence-evidence-insufficient'] };
  const numbers = frames.map((frame) => frame.imageNumber);
  if (new Set(numbers).size !== numbers.length || numbers.some((value, index) => value !== index + 1)) {
    return { status: 'manual-review', reasonCodes: ['sequence-order-ambiguous'] };
  }
  for (let index = 1; index < frames.length; index += 1) {
    const previous = new Set([...frames[index - 1].preservedState, ...frames[index - 1].changedState]);
    for (const required of frames[index].preservedState) {
      if (!previous.has(required)) return { status: 'manual-review', reasonCodes: ['preserved-state-unproven'] };
    }
  }
  return { status: 'pass', reasonCodes: [] };
}
