import { Header } from "@/components/layout/Header";
import { Reveal } from "@/components/layout/Reveal";
import { SmoothScroll } from "@/components/layout/SmoothScroll";
import { Hero } from "@/components/sections/Hero";

export default function Home() {
  return (
    <>
      <SmoothScroll />
      <Reveal />
      <Header />
      <main id="main" tabIndex={-1}>
        <Hero />
        {/* Statement band (step 6). For now only its sheet edge, which casts the shadow on the hero's lower edge. */}
        <div className="sheet-edge" aria-hidden="true">
          <div className="sheet-edge__flap board" />
        </div>
      </main>
    </>
  );
}
