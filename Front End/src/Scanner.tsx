import { useState } from "react";
import { Archive, Image } from "lucide-react";
import { Capture } from "./Capture";
import { PhotoBatch } from "./PhotoBatch";
import { loadLocal } from "./ui";
import { defaultStation, validStation } from "./station";

export function Scanner({ onSaved }: { onSaved: () => void }) {
  const [batch, setBatch] = useState(false);
  const [station, setStation] = useState(() =>
      loadLocal("remnantx.station.v1", defaultStation, validStation),
    ),
    [batchBusy, setBatchBusy] = useState(false);
  return (
    <>
      <div
        className="scan-mode segmented-control"
        aria-label="Photo import mode"
      >
        <button
          className={!batch ? "active" : ""}
          aria-pressed={!batch}
          disabled={batchBusy}
          onClick={() => setBatch(false)}
        >
          <Image size={15} />
          Single photo
        </button>
        <button
          className={batch ? "active" : ""}
          aria-pressed={batch}
          disabled={batchBusy}
          onClick={() => setBatch(true)}
        >
          <Archive size={15} />
          Batch photos / ZIP
        </button>
      </div>
      <div hidden={batch}>
        <Capture
          onSaved={onSaved}
          stationProfile={station}
          onStationProfileChange={setStation}
        />
      </div>
      <div hidden={!batch}>
        <PhotoBatch
          onSaved={onSaved}
          stationProfile={station}
          onStationProfileChange={setStation}
          onBusyChange={setBatchBusy}
        />
      </div>
    </>
  );
}
