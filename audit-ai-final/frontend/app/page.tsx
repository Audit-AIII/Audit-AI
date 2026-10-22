import { Header } from "@/components/layout/Header";
import { Reveal } from "@/components/layout/Reveal";
import { SmoothScroll } from "@/components/layout/SmoothScroll";
import { Hero } from "@/components/sections/Hero";
import { Statement } from "@/components/sections/Statement";

export default function Home() {
  return (
    <>
      <SmoothScroll />
      <Reveal />
      <Header />
      <main id="main" tabIndex={-1}>
        <Hero />
        <Statement />
      </main>
    </>
  );
}
