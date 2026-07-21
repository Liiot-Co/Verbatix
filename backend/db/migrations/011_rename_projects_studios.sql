-- Rename tables to match frontend terminology

-- Rename projects to studios (since it was representing Studio)
ALTER TABLE projects RENAME TO studios;

-- Rename proyectos to projects (since it was representing Project)
ALTER TABLE proyectos RENAME TO projects;

-- Note: We are keeping the foreign key column names as is (proyecto_id and project_id) 
-- to minimize the blast radius of this rename across the frontend and backend API.
-- The sqlalchemy models will map the column names explicitly.
