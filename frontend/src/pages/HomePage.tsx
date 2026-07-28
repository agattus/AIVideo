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
        <p className="brand-mark">AIVideo</p>
        <h1 className="headline">Turn one idea into a finished film.</h1>
        <p className="lede">
          Generate the script and voice here, then copy each visual prompt, upload your images,
          and assemble — on phone or desktop.
        </p>
        <GenerateForm />
      </section>
      <LibraryGrid />
    </>
  );
}
