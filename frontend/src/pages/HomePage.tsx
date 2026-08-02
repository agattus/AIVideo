import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { GenerateForm } from "../components/GenerateForm";
import { LibraryGrid } from "../components/LibraryGrid";

export function HomePage() {
  const location = useLocation();

  useEffect(() => {
    if (location.hash === "#library") {
      document.getElementById("library")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [location.hash]);

  return (
    <>
      <section className="hero">
        <p className="brand-mark">
          S-<span>Studio</span>
        </p>
        <p className="hero-chip">idea → voice → cut</p>
        <h1 className="headline">Drop an idea. Walk away with a film.</h1>
        <p className="lede">
          Script and voice land first. Lock your stills, tweak the vibe, hit assemble —
          phone or laptop, same flow.
        </p>
        <GenerateForm />
      </section>
      <LibraryGrid />
    </>
  );
}
