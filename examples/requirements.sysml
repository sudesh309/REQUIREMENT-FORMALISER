/* Sample requirements model with traceability fields. */

package VehicleRequirements {

    requirement def TopLevelRange id="REQ-001" {
        doc /* The vehicle shall have an electric range of at least 400 km. */
    }

    requirement def AccelerationTime id="REQ-002" {
        doc /* The vehicle shall reach 100 km/h within 6 seconds. */
    }

    requirement def MassBudget id="REQ-003" {
        doc /* Curb mass shall not exceed 1800 kg. */
    }
}
