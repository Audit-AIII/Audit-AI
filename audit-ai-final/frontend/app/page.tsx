import { ApprovalSeal } from "@/components/layout/ApprovalSeal";
import { Footer } from "@/components/layout/Footer";
import { Header } from "@/components/layout/Header";
import { LoopPause } from "@/components/layout/LoopPause";
import { Reveal } from "@/components/layout/Reveal";
import { SmoothScroll } from "@/components/layout/SmoothScroll";
import { Checks } from "@/components/sections/Checks";
import { Contact } from "@/components/sections/Contact";
import { Faq } from "@/components/sections/Faq";
import { Findings } from "@/components/sections/Findings";
import { Hero } from "@/components/sections/Hero";
import { Oversight } from "@/components/sections/Oversight";
import { Process } from "@/components/sections/Process";
import { Roles } from "@/components/sections/Roles";
import { Sources } from "@/components/sections/Sources";
import { Statement } from "@/components/sections/Statement";

/** Landing page, sections in DESIGN.md §15 order. */
export default function Home() {
  return (
    <>
      <SmoothScroll />
      <Reveal />
      <LoopPause />
      <Header />
      <main id="main" tabIndex={-1}>
        <Hero />
        <Statement />
        <div className="board sheet">
          <Checks />
          <Process />
          <Findings />
          <Oversight />
          <Sources />
          <Roles />
          <Faq />
          <Contact />
          <ApprovalSeal />
        </div>
      </main>
      <div className="board">
        <Footer />
      </div>
    </>
  );
}
