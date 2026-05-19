# Signature Templates

A **DSC Signature Template** controls the **visible signature stamp** — the box drawn
on the page showing who signed, when, and why. It does not affect the cryptographic
signature itself, only its appearance.

## What a template defines

### Visible content (stamp toggles)

A template can show or hide each element of the stamp:

- Signer name
- Designation
- A "Digitally signed by …" line
- Timestamp
- Reason
- Location

### Placement (DSC Signature Field rows)

Each **DSC Signature Field** row defines a rectangle: a **page number** and the
**x / y / width / height** of the stamp, in PDF points.

!!! info "Coordinate system"
    pyHanko uses PDF points with the **origin at the bottom-left** of the page. A US
    Letter page is 612 × 792 pt. `x`/`y` is the bottom-left corner of the stamp.

## The visual designer

The DSC Signature Template form provides a drag-and-drop designer so you do not have
to type coordinates:

1. Open a DSC Signature Template.
2. Use **Layout → Open Designer**.
3. In the modal:
   - **+ Add Field** adds a signature rectangle.
   - **Drag** a rectangle to move it; **drag the corner** to resize.
   - Switch **Page** to design on different pages.
   - Optionally load a **Reference PDF** to design against a real layout.
4. **Save & Close** writes the rectangles back into the field table.

A smaller read-only preview on the form always shows current placements on a scaled
page outline, and warns if any field extends off the page.

## How templates are used

| Context | How the template applies |
|---|---|
| [DSC Rule](signing-rules.md) signing | Position + content come from the template's first field |
| [DSC Document Sign](document-sign.md) | Position is placed interactively; the template only supplies stamp **content** |
| No template at all | A default stamp is used (signer name, designation, "digitally signed by", timestamp, reason, location) |

## Tips

- Keep stamp width/height generous enough for the content you enable — too small and
  text is clipped.
- For multi-signer documents, add one field per signer position.
- The designer's reference-PDF feature is the easiest way to get placement right for
  a specific print format.
</content>
