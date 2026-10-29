import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Boxes,
  Camera,
  ChevronRight,
  CircleHelp,
  LayoutGrid,
  Play,
  ScanLine,
  Settings2,
} from "lucide-react";
import { Plan } from "./Plan";
import { Scanner } from "./Scanner";
import { ExampleTour } from "./ExampleTour";
import { Inventory } from "./Inventory";
import { api } from "./api";
import { Busy, ErrorNotice, Modal, loadLocal } from "./ui";
import type { Recording, Remnant } from "./types";

export default function App() {
  const [tab, setTab] = useState(() =>
    loadLocal(
      "remnantx.view.v1",
      "Plan a job",
      (v): v is string =>
        typeof v === "string" &&
        ["Plan a job", "Scan a remnant", "Inventory"].includes(v),
    ),
  );
  const [example, setExample] = useState(() =>
      loadLocal(
        "remnantx.example.v1",
        true,
        (v): v is boolean => typeof v === "boolean",
      ),
    ),
    [tour, setTour] = useState(false);
  const [recording, setRecording] = useState<Recording | null>(null),
    [recordingError, setRecordingError] = useState("");
  const [inventory, setInventory] = useState<Remnant[]>([]),
    [loading, setLoading] = useState(false);
  const [inventoryError, setInventoryError] = useState(""),
    [connected, setConnected] = useState(false),
    [guide, setGuide] = useState(false);
  const refresh = async () => {
    setLoading(true);
    setInventoryError("");
    try {
      const data = await api.inventory();
      setInventory(data.remnants);
      setConnected(true);
    } catch (e) {
      setInventoryError((e as Error).message);
      setConnected(false);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    try {
      localStorage.setItem("remnantx.view.v1", JSON.stringify(tab));
      localStorage.setItem("remnantx.example.v1", JSON.stringify(example));
    } catch {
      /* The current view still works when browser storage is unavailable. */
    }
  }, [tab, example]);
  useEffect(() => {
    void api
      .health()
      .then(() => setConnected(true))
      .catch(() => setConnected(false));
    void refresh();
  }, []);
  useEffect(() => {
    void fetch("/example/recording.json")
      .then((response) => {
        if (!response.ok)
          throw new Error(
            "The recorded example could not be loaded. You can still use the live workspace.",
          );
        return response.json();
      })
      .then((data: Recording) => setRecording(data))
      .catch((e) => setRecordingError(e.message));
  }, []);
  return (
    <div className="app-shell">
      <aside className="rail">
        <a className="brand" href="/" aria-label="Remnant X home">
          <span className="brand-mark">
            <span />
          </span>
          <span>
            remnant<span className="brand-x">x</span>
            <small>THE MATERIAL WORKBENCH</small>
          </span>
        </a>
        <span className="rail-caption">WORKSPACE</span>
        <nav>
          {[
            { label: "Plan a job", icon: LayoutGrid },
            { label: "Scan a remnant", icon: ScanLine },
            { label: "Inventory", icon: Boxes },
          ].map((item) => (
            <button
              key={item.label}
              className={
                tab === item.label ? "rail-link selected" : "rail-link"
              }
              onClick={() => {
                setTab(item.label);
                if (item.label === "Scan a remnant") setExample(false);
              }}
              aria-current={tab === item.label ? "page" : undefined}
            >
              <item.icon size={18} />
              {item.label}
              {tab === item.label && <ChevronRight size={15} />}
            </button>
          ))}
        </nav>
        <div className="rail-note">
          <span className="rail-note-icon">
            <Camera size={19} />
          </span>
          <strong>Waste is a design problem.</strong>
          <p>Make something useful from what’s already there.</p>
        </div>
        <div className="rail-bottom">
          <button className="rail-link" onClick={() => setGuide(true)}>
            <CircleHelp size={17} />
            Workbench guide
            <ArrowUpRight size={14} />
          </button>
          <div className="avatar-row">
            <span className="avatar">RX</span>
            <div>
              Local workshop<small>Desktop workspace</small>
            </div>
            <Settings2 size={16} />
          </div>
        </div>
      </aside>
      <main
        className="main"
        onWheelCapture={(e) => {
          // Scrolling a long form must not change thickness, quantities or process values.
          if (
            e.target instanceof HTMLInputElement &&
            e.target.type === "number"
          )
            e.target.blur();
        }}
      >
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <span>{tab}</span>
          </div>
          <div className="topbar-actions">
            <div className="mode-switch" aria-label="Workspace mode">
              <button
                aria-pressed={example}
                onClick={() => {
                  setExample(true);
                  if (tab === "Scan a remnant") setTab("Plan a job");
                }}
              >
                Example
              </button>
              <button aria-pressed={!example} onClick={() => setExample(false)}>
                Live workspace
              </button>
            </div>
            <button
              className={`connection connection-button ${connected ? "" : "offline"}`}
              onClick={() => void refresh()}
            >
              <i />
              {connected ? "Backend connected" : "Backend offline · retry"}
            </button>
          </div>
        </header>
        <div className="page-heading">
          <div>
            <p className="eyebrow">LESS SCRAP. MORE POSSIBILITY.</p>
            <h1>
              {tab === "Plan a job" ? (
                <>
                  The sheet you have.
                  <br />
                  <span>The parts you need.</span>
                </>
              ) : tab === "Scan a remnant" ? (
                <>
                  Start with what’s left.
                  <br />
                  <span>See what’s possible.</span>
                </>
              ) : (
                <>
                  Useful material.
                  <br />
                  <span>Already in your workshop.</span>
                </>
              )}
            </h1>
            <p>
              {tab === "Plan a job"
                ? "From a remnant to a verified cutting plan, in one workspace."
                : tab === "Scan a remnant"
                  ? "A station photograph becomes geometry. The holes come with it."
                  : "Inspect your sheets, their cutouts and the space you can still use."}
            </p>
          </div>
          <div className="heading-actions">
            <button
              className="button primary"
              onClick={() => {
                setExample(false);
                setTab("Scan a remnant");
              }}
            >
              <ScanLine size={15} />
              Import stock <span className="button-detail">Photos / ZIP</span>
            </button>
            <button
              className="button secondary"
              disabled={!recording}
              onClick={() => {
                setExample(true);
                setTab("Plan a job");
                setTour(true);
              }}
            >
              <Play size={15} />
              {example ? "Guided walkthrough" : "Explore the example"}
              <ArrowUpRight size={15} />
            </button>
          </div>
        </div>
        <ErrorNotice message={example ? recordingError : ""} />
        <div hidden={tab !== "Plan a job"}>
          {example && !recording ? (
            recordingError ? (
              <button
                className="button primary"
                onClick={() => setExample(false)}
              >
                Open live workspace
              </button>
            ) : (
              <Busy label="Loading the recorded example" />
            )
          ) : (
            <Plan
              inventory={inventory}
              onInventoryChanged={() => void refresh()}
              onInventory={() => setTab("Inventory")}
              example={example}
              sample={recording ?? undefined}
              onLive={() => {
                setExample(false);
                setTab("Plan a job");
              }}
            />
          )}
        </div>
        <div hidden={tab !== "Scan a remnant"}>
          <Scanner onSaved={() => void refresh()} />
        </div>
        <div hidden={tab !== "Inventory"}>
          <Inventory
            remnants={
              example ? (recording?.result.candidate_sheets ?? []) : inventory
            }
            loading={!example && loading}
            error={example ? "" : inventoryError}
            onRefresh={() => void refresh()}
            onScan={() => {
              setExample(false);
              setTab("Scan a remnant");
            }}
            example={example}
          />
        </div>
        <footer className="page-footer">
          <span>Built for the material that’s already here.</span>
          <span>Perception → geometry → verified output</span>
        </footer>
      </main>
      {tour && recording && (
        <ExampleTour recording={recording} onClose={() => setTour(false)} />
      )}
      {guide && (
        <Modal
          title="One sheet. A second possibility."
          onClose={() => setGuide(false)}
        >
          <ol className="guide-list">
            <li>
              <strong>Set up the station.</strong>
              <p>
                Save the spans between the outer black-square edges and the
                printed black marker size. IDs 0–3 stay at their assigned
                corners.
              </p>
            </li>
            <li>
              <strong>Scan the remnant.</strong>
              <p>
                Choose a photo. Marker and calibration checks run before SAM.
                Supply the material grade and thickness; SAM extracts the
                outline and holes.
              </p>
            </li>
            <li>
              <strong>Plan and inspect.</strong>
              <p>
                Review a structured parts list, nest it against compatible stock
                and inspect the verified program. The system predicts stock
                changes; no machine is connected.
              </p>
            </li>
          </ol>
          <button
            className="button primary full"
            onClick={() => {
              setGuide(false);
              setExample(false);
              setTab("Scan a remnant");
            }}
          >
            Open scanner <ChevronRight size={15} />
          </button>
        </Modal>
      )}
    </div>
  );
}
