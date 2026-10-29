import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Pause,
  Play,
  X,
} from "lucide-react";
import { SheetViewer } from "./SheetViewer";
import type { Recording } from "./types";
import { formatNumber } from "./geometry";

const steps = [
  {
    label: "The starting point",
    title: "An offcut is still an opportunity.",
    body: "A sheet with an existing L-shaped cutout. All four station markers are visible, so its image can be rectified into millimetres.",
    note: "Synthetic station · 600 × 450 mm · 50 mm markers",
  },
  {
    label: "Recover the geometry",
    title: "Keep the shape. Keep the holes.",
    body: "The backend turns the mask into a polygon with its interior cutout preserved. Available material and empty space stay distinct.",
    note: "This recorded example uses local thresholding. Live photo indexing uses Meta SAM 3.1.",
  },
  {
    label: "Find room for the parts",
    title: "A small production run. An existing sheet.",
    body: "Plates, rings and discs are placed around the cutout by the real hole-aware nesting engine. The browser displays those returned placements.",
    note: "Recorded final placements · this animation is not a live optimization trace",
  },
  {
    label: "Verify the planned output",
    title: "A plan you can inspect.",
    body: "The final controller program passed the backend’s opcode, path and cut-order checks. Inspect the geometry and download the actual recorded output.",
    note: "Software verification covers planned geometry and commands. No machine is connected.",
  },
];
export function ExampleTour({
  recording,
  onClose,
}: {
  recording: Recording;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState(0),
    [playing, setPlaying] = useState(false);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous?.focus();
    };
  }, []);
  useEffect(() => {
    if (!playing) return;
    if (step === 3) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setStep((s) => s + 1), 5500);
    return () => clearTimeout(timer);
  }, [playing, step]);
  const result = recording.result,
    sheet = result.nesting.sheet_outcomes.find((s) => s.placed_parts.length)!;
  const stock = result.candidate_sheets.find(
    (s) => s.sheet_id === sheet.sheet_id,
  )!;
  const program = result.gcode_programs.find(
    (p) => p.sheet_id === sheet.sheet_id,
  );
  return (
    <dialog
      className="modal tour-modal"
      ref={dialog}
      aria-label="Recorded example walkthrough"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="tour-top">
        <span className="badge neutral">
          Recorded example · synthetic station
        </span>
        <button
          className="icon-button"
          aria-label="Close walkthrough"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <nav className="tour-steps" aria-label="Walkthrough chapters">
        {steps.map((s, i) => (
          <button
            key={s.label}
            aria-current={step === i ? "step" : undefined}
            onClick={() => {
              setStep(i);
              setPlaying(false);
            }}
          >
            <span>{i + 1}</span>
            {s.label}
          </button>
        ))}
      </nav>
      <div className="tour-content">
        <div className="tour-story">
          <span className="eyebrow">A SECOND LIFE, IN FOUR STEPS</span>
          <h2>{steps[step].title}</h2>
          <p>{steps[step].body}</p>
          <div className="tour-note">{steps[step].note}</div>
          {step === 3 && (
            <div className="tour-conclusion">
              <CheckCircle2 size={18} />
              <div>
                <strong>
                  {result.nesting.total_placed} parts.{" "}
                  {result.metrics.sheets_used} sheet.
                </strong>
                <small>
                  {formatNumber(result.metrics.usable_area_utilization_pct)}% of
                  usable material occupied
                </small>
              </div>
            </div>
          )}
        </div>
        <div className="tour-visual">
          {step === 0 ? (
            <figure>
              <img
                src="/example/station.png"
                alt="Synthetic indexing station with four ArUco markers and a sheet containing an L-shaped hole"
              />
              <figcaption>
                Generated test image. No private shop-floor photograph.
              </figcaption>
            </figure>
          ) : (
            <SheetViewer
              key={step}
              geometry={stock.geometry}
              parts={step >= 2 ? sheet.placed_parts : []}
              program={program}
              toolpath={step === 3}
              title={`Walkthrough: ${steps[step].label}`}
            />
          )}
        </div>
      </div>
      <div className="tour-bottom">
        <div>
          <button
            className="icon-button"
            aria-label={playing ? "Pause walkthrough" : "Play walkthrough"}
            onClick={() => {
              if (step === 3) setStep(0);
              setPlaying((v) => !v);
            }}
          >
            {playing ? <Pause size={15} /> : <Play size={15} />}
          </button>
          <span>{step + 1} / 4</span>
          <button
            className="icon-button"
            aria-label="Previous chapter"
            disabled={step === 0}
            onClick={() => {
              setStep((s) => s - 1);
              setPlaying(false);
            }}
          >
            <ArrowLeft size={15} />
          </button>
          <button
            className="icon-button"
            aria-label="Next chapter"
            disabled={step === 3}
            onClick={() => {
              setStep((s) => s + 1);
              setPlaying(false);
            }}
          >
            <ArrowRight size={15} />
          </button>
        </div>
        <button className="button primary" onClick={onClose}>
          View the complete result <ArrowRight size={14} />
        </button>
      </div>
    </dialog>
  );
}
