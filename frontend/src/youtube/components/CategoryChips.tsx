import { CATEGORY_CHIPS } from "../data/mockVideos";

type Props = {
  active: string;
  onChange: (chip: string) => void;
  extra?: string[];
};

export function CategoryChips({ active, onChange, extra = [] }: Props) {
  const chips = [...new Set([...extra, ...CATEGORY_CHIPS])];

  return (
    <div className="yt-chips" role="tablist" aria-label="Categories">
      {chips.map((chip) => (
        <button
          key={chip}
          type="button"
          role="tab"
          aria-selected={active === chip}
          className={`yt-chip${active === chip ? " active" : ""}`}
          onClick={() => onChange(chip)}
        >
          {chip}
        </button>
      ))}
    </div>
  );
}
