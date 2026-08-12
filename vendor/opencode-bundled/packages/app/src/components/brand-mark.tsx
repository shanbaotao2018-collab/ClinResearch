import clinicalResearchIcon from "@/assets/clinical-research-workbench-icon.png"

export function BrandMark(props: { class?: string }) {
  return <img src={clinicalResearchIcon} alt="" aria-hidden="true" class={props.class} />
}
